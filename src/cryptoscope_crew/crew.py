from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict

import os, re, pathlib, json



from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff,llm
from crewai import LLM
from crewai.project import llm as llm_decorator
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import SerperDevTool, MCPServerAdapter
from mcp import StdioServerParameters
from litellm.exceptions import ContentPolicyViolationError

from cryptoscope_crew.reporting.precompute import precompute, precompute_multi, ready_signals_from_context, ready_signals_multi, tech_table_from_context, triggers_from_context, precompute_flow, flow_summary_table, key_levels_table, coherence_note
from cryptoscope_crew.journal import save_task_output, validate_narrative_scan
from cryptoscope_crew.domain.portfolio import load_portfolio, sync_portfolio_from_exchange
from cryptoscope_crew.domain.decision_engine import decide_all, decisions_to_markdown
from cryptoscope_crew.domain.opportunities import OpportunityEngine, opportunities_to_markdown
from cryptoscope_crew.domain.regime import MarketRegimeDetector
from cryptoscope_crew.domain.macro_regime import BtcMacroRegimeDetector, MacroRegime
from cryptoscope_crew.domain.signal_engine import SignalEngine
from cryptoscope_crew.domain.portfolio_strategy import PortfolioStrategyEngine, portfolio_strategy_to_markdown

ALLOWS_TEMPERATURE = {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"}

# Modèle de repli si le principal déclenche une ContentPolicyViolation
_FALLBACK_MODEL = os.getenv("OPENAI_MODEL_FALLBACK", "gpt-4.1-mini")


class _FallbackLLM(LLM):
    """LLM avec fallback automatique sur ContentPolicyViolationError.

    Si le modèle principal refuse le prompt (content-policy), on retente
    une fois avec *_FALLBACK_MODEL* (env OPENAI_MODEL_FALLBACK).
    """

    def call(self, messages, **kwargs):
        try:
            return super().call(messages, **kwargs)
        except ContentPolicyViolationError as exc:
            original_model = self.model
            print(
                f"[WARN] ContentPolicyViolation avec {original_model}. "
                f"Fallback -> {_FALLBACK_MODEL}"
            )
            self.model = _FALLBACK_MODEL
            try:
                return super().call(messages, **kwargs)
            finally:
                self.model = original_model  # restaure pour les appels suivants

def _make_llm(model_env_fallback: str) -> LLM:
    model = os.getenv(model_env_fallback, os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"))
    kwargs = dict(model=model, api_key=os.getenv("OPENAI_API_KEY"))
    # on ne met temperature que si le modèle le supporte
    if any(model.startswith(m) for m in ALLOWS_TEMPERATURE):
        # valeur par défaut paramétrable, sinon 0.2
        t_env = os.getenv("OPENAI_TEMPERATURE")
        if t_env:
            try:
                t = float(t_env)
                kwargs["temperature"] = t
            except ValueError:
                pass
        else:
            kwargs["temperature"] = 0.2
    return _FallbackLLM(**kwargs)

# le même modèle pour tous:
def _llm_default() -> LLM:
    return _make_llm("OPENAI_MODEL_NAME")

# model par agent:
def _llm_researcher() -> LLM:
    return _make_llm("OPENAI_MODEL_RESEARCHER")

def _llm_technician() -> LLM:
    return _make_llm("OPENAI_MODEL_TECHNICIAN")

def _llm_analyst() -> LLM:
    return _make_llm("OPENAI_MODEL_ANALYST")


def _parse_pairs_env(val: str) -> list[str]:
    raw = re.split(r"[,\s;]+", val.strip())
    pairs = []
    for t in raw:
        if not t:
            continue
        p = t.upper()
        # tolère "BTCUSDC" -> "BTC/USDC"
        if "/" not in p and len(p) > 4:
            p = p[:-4] + "/" + p[-4:]
        pairs.append(p)
    # dédupe en gardant l'ordre
    seen, uniq = set(), []
    for p in pairs:
        if p not in seen:
            uniq.append(p); seen.add(p)
    return uniq

def _coerce_positive_int(val, default: int) -> int:
    try:
        n = int(str(val).strip()); return n if n > 0 else default
    except Exception:
        return default


def _tool_registry():
    return {
        "serper": SerperDevTool() if os.getenv("SERPER_API_KEY") else None,
        # "duckduckgo": DuckDuckGoSearchTool() ...
    }

def _membit_tools():
    """Initialize Membit MCP tools for Twitter/X analysis. Returns list or empty."""
    api_key = os.getenv("MEMBIT_API_KEY")
    if not api_key:
        print("[WARN] MEMBIT_API_KEY not set — social_scan disabled")
        return []
    try:
        server_params = StdioServerParameters(
            command="npx",
            args=[
                "mcp-remote",
                "https://mcp.membit.ai/mcp",
                "--header",
                f"X-Membit-Api-Key:{api_key}",
            ],
        )
        adapter = MCPServerAdapter(server_params)
        tools = adapter.tools
        print(f"[OK] Membit MCP: {len(tools)} tools loaded")
        return tools
    except Exception as e:
        print(f"[WARN] Membit MCP init failed: {e}")
        return []


def _tools_for(agent_name: str):
    reg = _tool_registry()
    mapping = {
        "researcher": ["serper"],
        "technician": [],
        "reporting_analyst": [],
    }
    names = mapping.get(agent_name, [])
    return [reg[n] for n in names if reg.get(n)]

def _lang_guard(lang: str) -> str:
    return "IMPORTANT: Réponds exclusivement en français. Si une partie est en anglais, retraduis-la en français."


def _format_social_section(data: dict) -> str:
    """Format social_scan JSON into a markdown section."""
    lines = ["## Social Sentiment (Twitter/X)", ""]

    # Sentiment overview
    sentiment = data.get("sentiment", {})
    label = sentiment.get("label", "?").upper()
    bull = sentiment.get("bull_pct", 0)
    bear = sentiment.get("bear_pct", 0)
    neutral = sentiment.get("neutral_pct", 0)
    lines.append(f"**Sentiment global :** {label} — 🟢 {bull}% bull / 🔴 {bear}% bear / ⚪ {neutral}% neutre")
    lines.append("")

    # Clusters
    clusters = data.get("clusters", [])
    if clusters:
        lines.append("### Clusters dominants")
        lines.append("| # | Sujet | Tickers | Momentum | Volume |")
        lines.append("|---|-------|---------|----------|--------|")
        for i, c in enumerate(clusters[:5], 1):
            tickers = ", ".join(c.get("tickers", []))
            mom = c.get("momentum", 0)
            vol = c.get("volume", "?")
            mom_bar = "█" * min(mom, 10) + "░" * (10 - min(mom, 10))
            lines.append(f"| {i} | {c.get('title', '?')} | {tickers} | {mom_bar} {mom}/10 | {vol} |")
        lines.append("")

    # Weak signals
    weak = data.get("weak_signals", [])
    if weak:
        lines.append("### Signaux faibles (émergents)")
        for w in weak[:3]:
            tickers = ", ".join(w.get("tickers", []))
            lines.append(f"- **{w.get('title', '?')}** ({tickers}) — {w.get('summary', '')} [momentum: {w.get('momentum', '?')}/10]")
        lines.append("")

    return "\n".join(lines)


@CrewBase
class CryptoscopeCrew:   

    agents: List[BaseAgent]
    tasks: List[Task]

    # ---------------------------------------------------------------------
    # Inputs runtime par défaut (surchargés par --inputs ou .env si fournis)
    # ---------------------------------------------------------------------
    @before_kickoff
    def inject_runtime_inputs(self, inputs: dict) -> dict:
        # ---------- TZ & horodatage ----------
        tz_name = inputs.get("tz", os.getenv("TZ", "Europe/Paris"))
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            print(f"[WARN] TZ '{tz_name}' introuvable. Fallback: UTC")
            tz = ZoneInfo("UTC"); tz_name = "UTC"
        now = datetime.now(tz)

        run_id = now.strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join("runs", run_id)
        pathlib.Path(run_dir).mkdir(parents=True, exist_ok=True)

        inputs["run_id"] = run_id
        inputs["run_dir"] = run_dir
        self._run_dir = run_dir          # accessible par les callbacks

        inputs.setdefault("lang", os.getenv("LANG", "fr"))
        inputs["tz"] = tz_name
        inputs.setdefault("report_date", now.strftime("%Y-%m-%d"))
        inputs.setdefault("report_time", now.strftime("%H:%M"))
        inputs.setdefault("report_iso",  now.isoformat())

        # --- Marché
        env_pairs = os.getenv("PAIRS", "")
        pairs = inputs.get("pairs") or (_parse_pairs_env(env_pairs) if env_pairs else ["BTC/USDC","ETH/USDC"])
        if isinstance(pairs, str):
            pairs = _parse_pairs_env(pairs)
        inputs["pairs"] = pairs
        inputs["pairs_display"] = ", ".join(pairs)
        inputs["pairs_json"] = json.dumps(pairs, ensure_ascii=False)

        # --- TF principal + secondaires
        tf_main = (inputs.get("timeframe") or os.getenv("TIMEFRAME") or "1d").lower()
        inputs["timeframe"] = tf_main

        tfs_env = os.getenv("TIMEFRAMES", "").strip()
        tf_list = [t.strip().lower() for t in tfs_env.split(",") if t.strip()] or [tf_main, "4h", "1h"]
        # forcer le principal en tête + dédupliquer
        tf_calc, seen = [], set()
        for tf in [tf_main] + tf_list:
            if tf not in seen:
                tf_calc.append(tf); seen.add(tf)
        inputs["timeframes"] = tf_calc
        inputs["timeframes_display"] = ", ".join(tf_calc)


        # --- lookback / sortie
        inputs["lookback"] = _coerce_positive_int(inputs.get("lookback", os.getenv("LOOKBACK", "450")), 450)
        outdir = inputs.get("output_dir", os.getenv("OUTPUT_DIR", "reports"))
        pathlib.Path(outdir).mkdir(parents=True, exist_ok=True)
        inputs["report_output_path"] = os.path.join(outdir, f"report_{now.strftime('%d%m%Y_%H%M')}.md")
        self._report_output_path = inputs["report_output_path"]  # pour _cb_reporting

       # --- header prêt à coller
        inputs["header_md"] = (
            f"**Timeframes :** {inputs['timeframes_display']} — **Paires :** {inputs['pairs_display']}\n"
            f"**Date :** {inputs['report_date']}  **Heure :** {inputs['report_time']}  "
            f"**ISO :** {inputs['report_iso']} (TZ: {inputs['tz']})"
        )

         # --- placeholders requis (fallbacks)
        inputs.setdefault("context_json", "{}")
        inputs.setdefault("tech_table_md", "(pas de table technique)")
        inputs.setdefault("tech_tables_md", "")
        inputs.setdefault("summary_table_md", "")
        inputs.setdefault("triggers_md", "")
        inputs.setdefault("ready_signals_md", "")

        # --- calcul multi-TF
        try:
            bundle = precompute_multi(pairs, tf_calc, inputs["lookback"])

            # principal
            if tf_main in bundle["context_by_tf"]:
                ctx_main = bundle["context_by_tf"][tf_main]
                tech_main = bundle["tables_by_tf"][tf_main]
                inputs["ready_signals_md"] = ready_signals_multi(
                    bundle["context_by_tf"],
                    order=inputs.get("timeframes", ["1d", "4h", "1h"])
                )
            else:
                # filet de sécurité
                single = precompute(pairs, tf_main, inputs["lookback"])
                ctx_main = single.get("context", single)
                tech_main = single.get("tech_table_md", tech_table_from_context(ctx_main))
                # fallback ready_signals mono-TF
                inputs["ready_signals_md"] = ready_signals_from_context(ctx_main)

            # injections communes
            inputs["context_json"]  = json.dumps(ctx_main, ensure_ascii=False)
            inputs["tech_table_md"] = tech_main
            inputs["triggers_md"]   = triggers_from_context(ctx_main)

            # autres TF + synthèse
            sections = []
            for tf in tf_calc:
                if tf == tf_main:
                    continue
                table = bundle["tables_by_tf"].get(tf)
                if table:
                    sections.append(f"### Table {tf}\n-----\n{table}\n-----")
            inputs["tech_tables_md"]  = "\n\n".join(sections)
            inputs["summary_table_md"] = bundle.get("summary_table_md", "")
            inputs["context_by_tf_json"] = json.dumps(bundle["context_by_tf"], ensure_ascii=False)
            self._context_by_tf_json = inputs["context_by_tf_json"]

            # --- Decision Engine (déterministe) ---
            try:
                portfolio = load_portfolio()
                # Sync live balances from Binance (overwrites quantity + avg_price)
                if os.getenv("PORTFOLIO_LIVE_SYNC", "1") == "1":
                    try:
                        portfolio = sync_portfolio_from_exchange(portfolio, pairs)
                    except Exception as sync_err:
                        print(f"[WARN] Binance sync failed (using static portfolio.json): {sync_err}")
                # Enrichir avec les prix courants (depuis le TF principal)
                prices = {p["pair"]: p["close"] for p in ctx_main.get("pairs", [])}
                portfolio.enrich_all(prices)

                # --- Regime detection ---
                # Local regimes (EMA20/EMA50 per pair)
                regimes = MarketRegimeDetector.detect_all(pairs, bundle["context_by_tf"])
                # Macro regimes (EMA50/EMA200 BTC-led hierarchy)
                macro_regimes = BtcMacroRegimeDetector.detect_all(pairs, bundle["context_by_tf"])
                btc_macro = next(
                    (m.macro for m in macro_regimes if m.pair.split("/")[0].upper() == "BTC"),
                    MacroRegime.TRANSITION,
                )

                decisions = decide_all(pairs, bundle["context_by_tf"], portfolio, regimes=regimes)
                inputs["decisions_md"] = decisions_to_markdown(decisions)
                # Sauvegarder dans run_dir
                dec_path = os.path.join(run_dir, "decisions.json")
                import pathlib as _p
                _p.Path(dec_path).write_text(
                    json.dumps([d.model_dump(mode="json") for d in decisions], indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                print(f"[OK] Decision engine: {len(decisions)} d\u00e9cisions -> {dec_path}")
                self._decisions_md = inputs["decisions_md"]

                # --- Top Opportunities (déterministe) ---
                try:
                    opps = OpportunityEngine.build_top3(
                        bundle["context_by_tf"], portfolio, decisions,
                    )
                    inputs["opportunities_md"] = opportunities_to_markdown(opps)
                    self._opportunities_md = inputs["opportunities_md"]
                    # Sauvegarder dans run_dir
                    opp_path = os.path.join(run_dir, "opportunities.json")
                    _p.Path(opp_path).write_text(
                        json.dumps([o.model_dump(mode="json") for o in opps], indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    print(f"[OK] Opportunities: {len(opps)} top -> {opp_path}")
                except Exception as oe:
                    print(f"[WARN] Opportunities engine failed: {oe}")
                    inputs["opportunities_md"] = (
                        "## Top Opportunities (V1)\n\n"
                        f"Opportunities indisponibles (erreur: {oe})"
                    )

                # --- Portfolio Strategy (déterministe) ---
                try:
                    # regimes already computed above (local + macro)

                    # --- Regime + Flow (funding, OI, CHOP) ---
                    try:
                        flow_results = precompute_flow(pairs, bundle["context_by_tf"])
                        inputs["flow_table_md"] = flow_summary_table(flow_results)
                        self._flow_table_md = inputs["flow_table_md"]
                        print(f"[OK] Regime+Flow: {len(flow_results)} pairs computed")
                    except Exception as fe:
                        print(f"[WARN] precompute_flow failed: {fe}")
                        flow_results = {}
                        inputs["flow_table_md"] = ""

                    signals = SignalEngine.analyze_all(
                        pairs, bundle["context_by_tf"], regimes,
                        btc_macro=btc_macro,
                        flow_results=flow_results,
                    )
                    strategy = PortfolioStrategyEngine.build(
                        portfolio, regimes, signals, decisions, bundle["context_by_tf"],
                        macro_regimes=macro_regimes,
                    )
                    inputs["portfolio_strategy_md"] = portfolio_strategy_to_markdown(strategy)
                    self._portfolio_strategy_md = inputs["portfolio_strategy_md"]
                    # Sauvegarder dans run_dir
                    strat_path = os.path.join(run_dir, "portfolio_strategy.json")
                    _p.Path(strat_path).write_text(
                        json.dumps(strategy.model_dump(mode="json"), indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    print(f"[OK] Portfolio strategy: {len(strategy.positions)} positions -> {strat_path}")
                except Exception as se:
                    print(f"[WARN] Portfolio strategy engine failed: {se}")
                    inputs["portfolio_strategy_md"] = (
                        "## Spot Portfolio Strategy\n\n"
                        f"Portfolio strategy indisponible (erreur: {se})"
                    )
            except Exception as e:
                print(f"[WARN] Decision engine failed: {e}")
                inputs["decisions_md"] = (
                    "## Decision Summary (V1)\n\n"
                    f"Decision Summary indisponible (parsing error: {e})"
                )

        except Exception as e:
            import traceback
            print(f"[WARN] precompute_multi failed: {e}. Fallback sur TF principal.")
            print(f"[WARN] Traceback:\n{traceback.format_exc()}")
            # fallbacks déjà posés

        inputs.setdefault("narratives_md", "")
        inputs.setdefault(
            "decisions_md",
            "## Decision Summary (V1)\n\nDecision Summary indisponible (parsing error)",
        )
        inputs.setdefault(
            "opportunities_md",
            "## Top Opportunities (V1)\n\nAucune opportunité identifiée.",
        )
        inputs.setdefault(
            "portfolio_strategy_md",
            "## Spot Portfolio Strategy\n\nPortfolio strategy indisponible.",
        )

        # --- Niveaux Clés (déterministe, indépendant du decision engine) ---
        try:
            ctx_by_tf = json.loads(inputs.get("context_by_tf_json", "{}"))
            inputs["key_levels_md"] = key_levels_table(ctx_by_tf, pivot_tf="4h")
        except Exception:
            inputs["key_levels_md"] = ""

        # --- Kronos Forecast (observation seulement — n'influence rien) ---
        inputs["kronos_md"] = ""
        if os.getenv("KRONOS_ENABLED", "1") == "1":
            try:
                from cryptoscope_crew.forecast.kronos import forecast_pairs, kronos_table_md
                forecasts = forecast_pairs(pairs)
                inputs["kronos_md"] = kronos_table_md(forecasts)
                if forecasts:
                    kr_path = os.path.join(run_dir, "kronos_forecast.json")
                    pathlib.Path(kr_path).write_text(
                        json.dumps([f.model_dump(mode="json") for f in forecasts],
                                   indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    print(f"[OK] Kronos: {len(forecasts)} forecasts -> {kr_path}")
            except Exception as ke:
                print(f"[WARN] Kronos forecast indisponible: {ke}")
        self._kronos_md = inputs["kronos_md"]

        # --- Always store enrichment sections on self for _cb_reporting ---
        self._decisions_md = inputs["decisions_md"]
        self._opportunities_md = inputs.get("opportunities_md", "")
        self._portfolio_strategy_md = inputs.get("portfolio_strategy_md", "")
        self._flow_table_md = inputs.get("flow_table_md", getattr(self, "_flow_table_md", ""))
        self._key_levels_md = inputs.get("key_levels_md", "")

        # --- Store TA tables on self for deterministic injection in callback ---
        self._tech_table_md = inputs.get("tech_table_md", "")
        self._tech_tables_md = inputs.get("tech_tables_md", "")
        self._summary_table_md = inputs.get("summary_table_md", "")
        self._triggers_md = inputs.get("triggers_md", "")
        self._ready_signals_md = inputs.get("ready_signals_md", "")
        self._precompute_ok = bool(self._tech_table_md and self._tech_table_md != "(pas de table technique)")

        # (debug facultatif)
        print("TF main:", tf_main)
        print("TIMEFRAMES:", os.getenv("TIMEFRAMES","<none>"))
        print("Tables multi présentes?:", bool(inputs["tech_tables_md"]))
        print("Len summary_table_md:", len(inputs["summary_table_md"]))

        return inputs

    # ------------------------------------------------------------------ #
    #  Callbacks – run journal + validation
    # ------------------------------------------------------------------ #
    def _cb_scan_market(self, output) -> None:
        """Sauvegarde brute de la sortie scan_market."""
        save_task_output("scan_market", output.raw, self._run_dir)

    def _cb_narrative_scan(self, output) -> None:
        """Valide le JSON narrative_scan via Pydantic + sauvegarde."""
        validated = validate_narrative_scan(output.raw, self._run_dir)
        # Injecte le résultat validé comme attribut pour usage aval
        self._narrative_validated = validated

    def _cb_social_scan(self, output) -> None:
        """Parse et sauvegarde la sortie social_scan (Membit)."""
        save_task_output("social_scan", output.raw, self._run_dir)
        # Parse JSON pour construire la section markdown
        try:
            raw = output.raw.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            data = json.loads(raw)
            self._social_data = data
            self._social_md = _format_social_section(data)
            print(f"[OK] social_scan: sentiment={data.get('sentiment', {}).get('label', '?')}, "
                  f"{len(data.get('clusters', []))} clusters")
        except Exception as e:
            print(f"[WARN] social_scan parse failed: {e}")
            self._social_md = ""

    def _cb_tech_review(self, output) -> None:
        """Sauvegarde brute de la sortie tech_review."""
        save_task_output("tech_review", output.raw, self._run_dir)

    def _cb_reporting(self, output) -> None:
        """Copie le report final + decisions dans run_dir ET reports/.

        Architecture: les sections numériques sont TOUJOURS injectées par le code,
        indépendamment de ce que le LLM a écrit. Cela garantit que les données
        réelles apparaissent même si le LLM hallucine.
        """
        import pathlib as _p
        llm_narrative = output.raw

        # ============================================================
        # SECTION 1: Header (déjà dans le LLM output normalement)
        # ============================================================
        report = llm_narrative

        # ============================================================
        # SECTION 2: Tables TA déterministes (injectées inconditionnellement)
        # Si precompute a réussi, on remplace la section "Configuration technique"
        # du LLM par les vraies données.
        # ============================================================
        precompute_ok = getattr(self, "_precompute_ok", False)
        if precompute_ok:
            ta_block = self._build_ta_block()
            report = report.rstrip() + "\n\n" + ta_block
        else:
            report = report.rstrip() + (
                "\n\n## ⚠️ Données techniques indisponibles\n\n"
                "Le calcul des indicateurs (EMA/RSI/ATR) a échoué pour cette exécution. "
                "Les sections TA ci-dessus sont générées par le LLM SANS données réelles — "
                "**ne pas trader sur ces informations**. Relancer `make run` quand l'API est accessible."
            )

        # ============================================================
        # SECTION 3: Décisions + Opportunités + Portfolio Strategy
        # ============================================================
        decisions_md = getattr(self, "_decisions_md", "")
        if decisions_md:
            report = report.rstrip() + "\n\n" + decisions_md
        opportunities_md = getattr(self, "_opportunities_md", "")
        if opportunities_md:
            report = report.rstrip() + "\n\n" + opportunities_md
        portfolio_strategy_md = getattr(self, "_portfolio_strategy_md", "")
        if portfolio_strategy_md:
            report = report.rstrip() + "\n\n" + portfolio_strategy_md

        # ============================================================
        # SECTION 4: Niveaux Clés + Regime + Flow
        # ============================================================
        key_levels_md = getattr(self, "_key_levels_md", "")
        if key_levels_md:
            report = report.rstrip() + "\n\n" + key_levels_md
        flow_table_md = getattr(self, "_flow_table_md", "")
        if flow_table_md:
            report = report.rstrip() + "\n\n## Regime + Flow\n\n" + flow_table_md
        # Kronos (observation) — affiché pour évaluation, jamais utilisé en décision
        kronos_md = getattr(self, "_kronos_md", "")
        if kronos_md:
            report = report.rstrip() + "\n\n" + kronos_md

        # ============================================================
        # SECTION 5: Social Sentiment + Coherence check
        # ============================================================
        social_md = getattr(self, "_social_md", "")
        if social_md:
            report = report.rstrip() + "\n\n" + social_md
        # Coherence check (social vs technique)
        social_data = getattr(self, "_social_data", {})
        social_label = social_data.get("sentiment", {}).get("label", "")
        if social_label and precompute_ok:
            try:
                ctx_by_tf = json.loads(
                    getattr(self, "_context_by_tf_json", "{}")
                )
                note = coherence_note(ctx_by_tf, social_label, pivot_tf="4h")
                if note:
                    report = report.rstrip() + "\n\n" + note
            except Exception:
                pass

        # ============================================================
        # Write files
        # ============================================================
        # 1) Copie dans run_dir
        dest = os.path.join(self._run_dir, "report.md")
        _p.Path(dest).write_text(report, encoding="utf-8")
        print(f"[FILE] Report copié -> {dest}")
        # 2) Écraser le output_file (reports/) pour inclure les sections déterministes
        report_output = getattr(self, "_report_output_path", "")
        if report_output:
            _p.Path(report_output).parent.mkdir(parents=True, exist_ok=True)
            _p.Path(report_output).write_text(report, encoding="utf-8")
            print(f"[FILE] Report principal mis à jour -> {report_output}")

    def _build_ta_block(self) -> str:
        """Construit le bloc TA déterministe à injecter dans le rapport."""
        sections = []

        # Table principale (1D)
        tech_main = getattr(self, "_tech_table_md", "")
        if tech_main and tech_main != "(pas de table technique)":
            sections.append(
                "## Configuration technique (données réelles)\n-----\n"
                + tech_main + "\n-----"
            )

        # Synthèse multi-TF
        summary = getattr(self, "_summary_table_md", "")
        if summary:
            sections.append(
                "## Synthèse multi-timeframe\n-----\n"
                + summary + "\n-----"
            )

        # Tables secondaires (4h, 1h)
        tech_tables = getattr(self, "_tech_tables_md", "")
        if tech_tables:
            sections.append(tech_tables)

        # Signaux prêts à tirer
        ready = getattr(self, "_ready_signals_md", "")
        if ready:
            sections.append("## Signaux prêts à tirer\n" + ready)

        # Triggers par paire
        triggers = getattr(self, "_triggers_md", "")
        if triggers:
            sections.append("## Triggers par paire\n" + triggers)

        return "\n\n".join(sections)

    # -------------
    # Agents
    # -------------
    @agent
    def researcher(self) -> Agent:
        # Nécessite une entrée 'researcher' dans agents.yaml
        return Agent(
            config=self.agents_config["researcher"],  # type: ignore[index]
            verbose=True,
            tools=_tools_for("researcher"),
            llm=_llm_researcher(),
            instructions=[_lang_guard("fr")],
            
        )

    @agent
    def technician(self) -> Agent:
        # Nécessite 'technician' dans agents.yaml
        return Agent(
            config=self.agents_config["technician"],  # type: ignore[index]
            verbose=True,
            llm=_llm_technician(),
            instructions=[_lang_guard("fr")],
            
        )

 
    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["reporting_analyst"],
            verbose=True,            
            llm=_llm_analyst(),
            instructions=[_lang_guard("fr")],
        )

    @agent
    def narrative_hunter(self) -> Agent:
        membit = _membit_tools()
        return Agent(
            config=self.agents_config["narrative_hunter"],
            verbose=True,
            tools=membit,
            llm=_llm_researcher(),
            instructions=[_lang_guard("fr")],
        )
    
    # -------------
    # Tasks
    # -------------
    @task
    def scan_market(self) -> Task:
        # Nécessite 'scan_market' dans tasks.yaml
        return Task(
            config=self.tasks_config["scan_market"],  # type: ignore[index]
            agent=self.researcher(),
            callback=self._cb_scan_market,
        )

    @task
    def narrative_scan(self) -> Task:
        return Task(
            config=self.tasks_config["narrative_scan"],  
            agent=self.researcher(),
            callback=self._cb_narrative_scan,
        )

    @task
    def social_scan(self) -> Task:
        return Task(
            config=self.tasks_config["social_scan"],
            agent=self.narrative_hunter(),
            callback=self._cb_social_scan,
        )

    @task
    def tech_review(self) -> Task:
        # Nécessite 'tech_review' dans tasks.yaml
        return Task(
            config=self.tasks_config["tech_review"],  # type: ignore[index]
            agent=self.technician(),
            callback=self._cb_tech_review,
        )

    
    def compose_report(self) -> Task:
        # Nécessite 'compose_report' dans tasks.yaml
        return Task(
            config=self.tasks_config["compose_report"],  # type: ignore[index]
            agent=self.writer(),
            output_file="report.md",  # génère un fichier à la fin (facile à retrouver)
        )
    
    
    
    
    def reporting_task_nono(self) -> Task:
        return Task(
            config=self.tasks_config["reporting_task"],
            agent=self.reporting_analyst(),
            output_file="{run_dir}/report.md",  # génère un fichier à la fin (facile à retrouver)
        )
    
    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config["reporting_task"],
            # ⬇️ on passe la sortie des tasks précédentes au writer
            context=[
                self.scan_market(),     # catalyseurs
                self.narrative_scan(),  # narratifs news
                self.social_scan(),     # narratifs Twitter/X (Membit)
                self.tech_review(),     # notes techniques
            ],
            callback=self._cb_reporting,          # écrit run_dir/ + reports/
        )


    # -------------
    # Crew
    # -------------
    @crew
    def crew(self) -> Crew:
        """
        Crée la crew : process séquentiel (scan → tech → rédaction).
        """
        return Crew(
            agents=self.agents,  # auto-créés par les décorateurs @agent
            tasks=self.tasks,    # auto-créées par les décorateurs @task
            process=Process.sequential,           
            verbose=True,
            
        )

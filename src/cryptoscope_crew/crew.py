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
from crewai_tools import SerperDevTool

from cryptoscope_crew.reporting.precompute import precompute, precompute_multi, ready_signals_from_context, ready_signals_multi, tech_table_from_context, triggers_from_context

ALLOWS_TEMPERATURE = {"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"}

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
    return LLM(**kwargs)

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
            print(f"⚠️ TZ '{tz_name}' introuvable. Fallback: UTC")
            tz = ZoneInfo("UTC"); tz_name = "UTC"
        now = datetime.now(tz)

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

        except Exception as e:
            print(f"⚠️ precompute_multi failed: {e}. Fallback sur TF principal.")
            # fallbacks déjà posés

        inputs.setdefault("narratives_md", "")

        # (debug facultatif)
        print("TF main:", tf_main)
        print("TIMEFRAMES:", os.getenv("TIMEFRAMES","<none>"))
        print("Tables multi présentes?:", bool(inputs["tech_tables_md"]))
        print("Len summary_table_md:", len(inputs["summary_table_md"]))

        return inputs
   
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
    
    # -------------
    # Tasks
    # -------------
    @task
    def scan_market(self) -> Task:
        # Nécessite 'scan_market' dans tasks.yaml
        return Task(
            config=self.tasks_config["scan_market"],  # type: ignore[index]
            agent=self.researcher(),  # explicite si tu veux forcer l’agent
        )

    @task
    def narrative_scan(self) -> Task:
        return Task(
            config=self.tasks_config["narrative_scan"],  
            agent=self.researcher(),
        )

    @task
    def tech_review(self) -> Task:
        # Nécessite 'tech_review' dans tasks.yaml
        return Task(
            config=self.tasks_config["tech_review"],  # type: ignore[index]
            agent=self.technician(),
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
            output_file="{report_output_path}",
        )
    
    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config["reporting_task"],
            # ⬇️ on passe la sortie des tasks précédentes au writer
            context=[
                self.scan_market(),     # catalyseurs
                self.narrative_scan(),  # narratifs
                self.tech_review(),     # notes techniques
            ],
            output_file="{report_output_path}",  # ta fonction existante / ou {report_output_path}
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

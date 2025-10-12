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

from cryptoscope_crew.reporting.precompute import precompute

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
        n = int(str(val).strip())
        return n if n > 0 else default
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


@CrewBase
class CryptoscopeCrew:   

    agents: List[BaseAgent]
    tasks: List[Task]

    # ---------------------------------------------------------------------
    # Inputs runtime par défaut (surchargés par --inputs ou .env si fournis)
    # ---------------------------------------------------------------------
    @before_kickoff
    def inject_runtime_inputs(self, inputs: Dict) -> Dict:
        # ---- TZ + timestamps 
        tz_name = inputs.get("tz", os.getenv("TZ", "Europe/Paris"))
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            print(f"⚠️ TZ '{tz_name}' introuvable. Fallback: UTC")
            tz = ZoneInfo("UTC")
            tz_name = "UTC"

        now = datetime.now(tz)
        inputs.setdefault("report_date", now.strftime("%Y-%m-%d"))
        inputs.setdefault("report_time", now.strftime("%H:%M"))
        inputs.setdefault("report_iso",  now.isoformat())
        inputs["tz"] = tz_name  # force la valeur finale

        # ---- Langue
        inputs.setdefault("lang", os.getenv("LANG", "fr"))

        # ---- PAIRS depuis .env si non fournis en inputs
        if "pairs" in inputs and inputs["pairs"]:
            pairs = inputs["pairs"]
            if isinstance(pairs, str):
                pairs = _parse_pairs_env(pairs)
        else:
            env_pairs = os.getenv("PAIRS", "")
            pairs = _parse_pairs_env(env_pairs) if env_pairs else ["BTC/USDT","ETH/USDT","XRP/USDT"]

        inputs["pairs"] = pairs
        inputs["pairs_display"] = ", ".join(pairs)
        inputs["pairs_json"] = json.dumps(pairs)

        # ---- TIMEFRAME priorité: inputs > .env > default
        timeframe = inputs.get("timeframe") or os.getenv("TIMEFRAME") or "1d"
        inputs["timeframe"] = timeframe

        # ---- LOOKBACK priorité: inputs > .env > default (entier positif)
        lookback = inputs.get("lookback")
        if lookback is None:
            lookback = os.getenv("LOOKBACK", "500")
        inputs["lookback"] = _coerce_positive_int(lookback, 500)

        # ---- pré-calcules le contexte/table
        bundle = precompute(inputs["pairs"], inputs["timeframe"], inputs["lookback"])
        inputs.update(bundle)

        # ---- fichier de sortie daté (si pas déjà fait)
        fname = f"report_{now.strftime('%d%m%Y_%H%M')}.md"
        outdir = inputs.get("output_dir", os.getenv("OUTPUT_DIR", "reports"))
        pathlib.Path(outdir).mkdir(parents=True, exist_ok=True)
        safe_fname = re.sub(r'[^A-Za-z0-9._-]', '_', fname)
        inputs["report_output_path"] = os.path.join(outdir, safe_fname)

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
            
        )

    @agent
    def technician(self) -> Agent:
        # Nécessite 'technician' dans agents.yaml
        return Agent(
            config=self.agents_config["technician"],  # type: ignore[index]
            verbose=True,
            llm=_llm_technician(),
            
        )

 
    @agent
    def reporting_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["reporting_analyst"],
            verbose=True,
            tools=[SerperDevTool()],
            llm=_llm_analyst(),
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
    
    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config["reporting_task"],
            agent=self.reporting_analyst(),
            output_file="{report_output_path}",
        )

    # -------------
    # Crew
    # -------------
    @crew
    def crew(self) -> Crew:
        """
        Crée la crew : process séquentiel (scan → tech → rédaction).
        Si tu préfères un planner hiérarchique, passe à Process.hierarchical.
        """
        return Crew(
            agents=self.agents,  # auto-créés par les décorateurs @agent
            tasks=self.tasks,    # auto-créées par les décorateurs @task
             process=Process.sequential,           
            verbose=True,
        )

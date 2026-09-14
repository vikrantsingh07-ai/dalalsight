"""The Derivatives (F&O) analyst and Indian data tools are wired through graph, routing and reports."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.utils.agent_utils import derivatives_report_line
from tradingagents.dataflows import interface, stocktwits
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.analyst_execution import build_analyst_execution_plan
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree


@pytest.mark.unit
def test_execution_plan_and_router_know_the_derivatives_analyst():
    spec = build_analyst_execution_plan(["market", "derivatives"]).specs[1]
    assert (spec.agent_node, spec.tool_node, spec.report_key) == (
        "Derivatives Analyst", "tools_derivatives", "derivatives_report"
    )
    logic = ConditionalLogic()
    calling = {"messages": [AIMessage(content="", tool_calls=[{"name": "get_india_vix", "args": {}, "id": "1"}])]}
    done = {"messages": [AIMessage(content="report")]}
    assert logic.should_continue_derivatives(calling) == "tools_derivatives"
    assert logic.should_continue_derivatives(done) == "Msg Clear Derivatives"


@pytest.mark.unit
def test_tool_nodes_register_indian_tools():
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    assert set(nodes["derivatives"].tools_by_name) == {
        "get_fno_futures_analysis", "get_option_chain_analysis",
        "get_fii_derivatives_positioning", "get_india_vix",
    }
    assert "get_delivery_analysis" in nodes["market"].tools_by_name
    assert "get_fii_dii_cash_flows" in nodes["news"].tools_by_name
    assert "get_corporate_events" in nodes["fundamentals"].tools_by_name


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker,benchmark",
    [("NIFTY26SEPFUT", "^NSEI"), ("GOLD.MCX", "^NSEI"), ("USDINR", "^NSEI"),
     ("SENSEX26OCTFUT", "^BSESN"), ("500325.BO", "^BSESN"), ("AAPL", "SPY")],
)
def test_indian_benchmarks(ticker, benchmark):
    graph = SimpleNamespace(config={"benchmark_ticker": None, "benchmark_map": DEFAULT_CONFIG["benchmark_map"]})
    assert TradingAgentsGraph._resolve_benchmark(graph, ticker) == benchmark


@pytest.mark.unit
def test_initial_state_and_report_line():
    state = Propagator().create_initial_state("NIFTY-OPT", "2026-09-11", asset_type="options")
    assert state["derivatives_report"] == ""
    assert derivatives_report_line(state) == ""
    assert derivatives_report_line({"derivatives_report": "PCR 1.2"}) == "Derivatives (F&O) positioning report: PCR 1.2\n"


@pytest.mark.unit
def test_indian_categories_degrade_instead_of_crashing(monkeypatch):
    broken = MagicMock(side_effect=RuntimeError("NSE down"))
    monkeypatch.setitem(interface.VENDOR_METHODS, "get_option_chain_analysis", {"nse": broken})
    out = interface.route_to_vendor("get_option_chain_analysis", "NIFTY", "2026-09-11")
    assert out.startswith("DATA_UNAVAILABLE")


@pytest.mark.unit
def test_report_tree_includes_derivatives(tmp_path):
    write_report_tree({"derivatives_report": "OI walls at 24000"}, "NIFTY", tmp_path)
    assert (tmp_path / "1_analysts" / "derivatives.md").read_text(encoding="utf-8") == "OI walls at 24000"
    assert "Derivatives Analyst" in (tmp_path / "complete_report.md").read_text(encoding="utf-8")


@pytest.mark.unit
@pytest.mark.parametrize(
    "ticker,expected",
    [("RELIANCE.NS", "RELIANCE.NSE"), ("RELIANCE26SEPFUT", "RELIANCE.NSE"), ("NIFTY", None), ("GOLD.MCX", None)],
)
def test_stocktwits_symbols_for_indian_instruments(ticker, expected):
    assert stocktwits._stocktwits_symbol(ticker) == expected


@pytest.mark.unit
def test_derivatives_toolnode_executes_every_tool_call(monkeypatch):
    from langgraph.graph import END, START, MessagesState, StateGraph

    import tradingagents.agents.utils.india_data_tools as india_tools

    seen = []

    def fake_route(method, *args):
        seen.append((method, args))
        return f"{method} ok"

    monkeypatch.setattr(india_tools, "route_to_vendor", fake_route)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", TradingAgentsGraph._create_tool_nodes(None)["derivatives"])
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    request = AIMessage(content="", tool_calls=[
        {"name": "get_fno_futures_analysis", "args": {"symbol": "NIFTY26SEPFUT", "curr_date": "2026-09-11"}, "id": "1"},
        {"name": "get_option_chain_analysis", "args": {"symbol": "NIFTY-OPT", "curr_date": "2026-09-11"}, "id": "2"},
        {"name": "get_fii_derivatives_positioning", "args": {"curr_date": "2026-09-11"}, "id": "3"},
        {"name": "get_india_vix", "args": {"curr_date": "2026-09-11"}, "id": "4"},
    ])

    out = graph.compile().invoke({"messages": [request]})

    assert [m.content for m in out["messages"] if m.type == "tool"] == [
        "get_fno_futures_analysis ok",
        "get_option_chain_analysis ok",
        "get_fii_derivatives_positioning ok",
        "get_india_vix ok",
    ]
    assert ("get_fno_futures_analysis", ("NIFTY26SEPFUT", "2026-09-11", 10)) in seen

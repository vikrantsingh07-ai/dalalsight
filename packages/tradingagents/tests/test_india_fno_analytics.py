"""Indian F&O and cash-market analytics on synthetic exchange files (no network)."""

import io
from datetime import date, timedelta

import pandas as pd
import pytest

from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.india import cash_market, fno, nse_client

_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
    "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
    "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
    "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)


def _row(day, kind, symbol, expiry, strike, side, name, close, previous, spot, oi, oi_change, volume, lot=50):
    return (
        f"{day},{day},FO,NSE,{kind},1,,{symbol},,{expiry},{expiry},{strike},{side},{name},0,0,0,"
        f"{close},{close},{previous},{spot},{close},{oi},{oi_change},{volume},0,0,F1,{lot},,,,,"
    )


def _bhavcopy(day: str, future_close: float, future_prev: float, spot: float, oi: int, oi_change: int) -> pd.DataFrame:
    rows = [
        _row(day, "IDF", "NIFTY", "2026-09-29", "", "", "NIFTY26SEPFUT", future_close, future_prev, spot, oi, oi_change, 40),
        _row(day, "IDF", "NIFTY", "2026-10-27", "", "", "NIFTY26OCTFUT", future_close + 1, future_prev + 1, spot, 1000, 100, 5),
        # Weekly expiry option chain: OI in units (lot 50).
        _row(day, "IDO", "NIFTY", "2026-09-15", "90.00", "CE", "NIFTY2691590CE", 11.5, 11.0, spot, 1000, 0, 10),
        _row(day, "IDO", "NIFTY", "2026-09-15", "100.00", "CE", "NIFTY26915100CE", 4.0, 4.5, spot, 5000, 1000, 80),
        _row(day, "IDO", "NIFTY", "2026-09-15", "110.00", "CE", "NIFTY26915110CE", 0.8, 1.0, spot, 20000, 5000, 60),
        _row(day, "IDO", "NIFTY", "2026-09-15", "90.00", "PE", "NIFTY2691590PE", 0.5, 0.7, spot, 15000, 2500, 50),
        _row(day, "IDO", "NIFTY", "2026-09-15", "100.00", "PE", "NIFTY26915100PE", 3.0, 3.2, spot, 6000, -500, 90),
        _row(day, "IDO", "NIFTY", "2026-09-15", "110.00", "PE", "NIFTY26915110PE", 9.5, 9.0, spot, 500, 0, 5),
    ]
    return fno.parse_fo_bhavcopy(("\n".join([_HEADER, *rows]) + "\n").encode())


@pytest.fixture
def two_sessions(monkeypatch):
    sessions = [
        (date(2026, 9, 11), _bhavcopy("2026-09-11", 101.0, 100.0, 100.5, 5000, 500)),
        (date(2026, 9, 10), _bhavcopy("2026-09-10", 100.0, 99.0, 99.8, 4500, 200)),
    ]

    def fake_sessions(as_of, wanted, exchange="NSE"):
        return [s for s in sessions if s[0] <= as_of][:wanted]

    monkeypatch.setattr(fno, "recent_fo_sessions", fake_sessions)
    return sessions


@pytest.mark.unit
def test_black_scholes_implied_volatility_round_trip():
    price = fno.bs_price(100, 100, 0.25, 0.065, 0.2, "CE")
    assert fno.implied_volatility(price, 100, 100, 0.25, 0.065, "CE") == pytest.approx(0.2, abs=1e-3)
    assert fno.implied_volatility(0.01, 100, 50, 0.25, 0.065, "CE") is None  # below intrinsic
    call = fno.option_greeks(100, 100, 0.25, 0.065, 0.2, "CE")
    put = fno.option_greeks(100, 100, 0.25, 0.065, 0.2, "PE")
    assert call["delta"] - put["delta"] == pytest.approx(1.0)
    assert call["gamma"] == pytest.approx(put["gamma"])


@pytest.mark.unit
@pytest.mark.parametrize(
    "price,oi,expected",
    [(1.0, 10, "Long build-up"), (-1.0, 10, "Short build-up"), (1.0, -10, "Short covering"),
     (-1.0, -10, "Long unwinding"), (1.0, 0, "No clear build-up"), (None, 5, "No clear build-up")],
)
def test_buildup_classification(price, oi, expected):
    assert fno.classify_buildup(price, oi) == expected


@pytest.mark.unit
def test_chain_metrics_pcr_max_pain_and_straddle():
    frame = _bhavcopy("2026-09-11", 101.0, 100.0, 101.0, 5000, 500)
    options = frame[frame["FinInstrmTp"] == "IDO"]
    chain = fno.build_option_chain(options)
    assert chain.loc[110.0, "ce_oi"] == 400  # 20000 units / lot 50
    metrics = fno.chain_metrics(chain, 101.0, 4, 0.065)
    assert metrics["pcr_oi"] == pytest.approx(430 / 520)
    assert metrics["max_pain"] == 100.0
    assert metrics["atm"] == 100.0
    assert metrics["straddle"] == pytest.approx(7.0)
    assert metrics["implied_move_pct"] == pytest.approx(7.0 / 101.0 * 100)


@pytest.mark.unit
def test_futures_analysis_reports_buildup_basis_and_ladder(two_sessions):
    report = fno.futures_analysis("NIFTY26SEPFUT", "2026-09-11", 5)
    assert "Long build-up" in report
    assert "2026-10-27" in report  # expiry ladder
    assert "Requested contract NIFTY26SEPFUT" in report
    assert "contracts" in report


@pytest.mark.unit
def test_futures_analysis_for_stock_outside_fno(two_sessions):
    report = fno.futures_analysis("RELIANCE.NS", "2026-09-11")
    assert "not in the derivatives segment" in report


@pytest.mark.unit
def test_option_chain_analysis_with_contract_section(two_sessions):
    report = fno.option_chain_analysis("NIFTY26915100CE", "2026-09-11")
    assert "Max pain: 100" in report
    assert "Requested contract NIFTY26915100CE" in report
    assert "Breakeven at expiry 104.00" in report
    assert "premium per lot ≈ ₹200" in report


@pytest.mark.unit
def test_derivative_tools_explain_unsupported_instruments():
    assert "MCX" in fno.option_chain_analysis("GOLD.MCX", "2026-09-11")
    assert "currency" in fno.futures_analysis("USDINR", "2026-09-11").lower()
    assert "no exchange-traded futures" in fno.futures_analysis("NIFTYIT", "2026-09-11")


_PARTICIPANT_OI = '''""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Sep 11, 2026"",,,,,,,,,,,,,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts      ,Total Short Contracts
Client,286353,54865,3478897,213571,3847943,3126037,3618281,3879158,2716400,819413,1427016,1225584,14275043,10418475
DII,43743,29395,352254,4643802,5401,56824,3350,0,4876,44620,384382,22696,507718,5083625
FII,41252,326134,3454581,2934979,675792,1331606,962890,661895,182248,371833,415155,174485,6057312,5475538
Pro,66613,27567,897564,390944,1175140,1180310,1119754,1153725,934985,1075568,1611956,888669,5330180,5192615
TOTAL,437961,437961,8183296,8183296,5704276,5694777,5704276,5694777,3838509,2311434,3838509,2311434,26170253,26170253
'''


@pytest.mark.unit
def test_participant_oi_parse_and_report(monkeypatch):
    frame = fno.parse_participant_oi(_PARTICIPANT_OI)
    assert frame.loc["FII", "Future Index Short"] == 326134
    monkeypatch.setattr(fno, "load_participant_oi", lambda day: frame if day.weekday() < 5 else None)
    report = fno.participant_oi_analysis("2026-09-11", 2)
    assert "| FII | 41,252 | 326,134 | -284,882 | 11.2 |" in report


_SECURITY_BHAVDATA = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
RELIANCE, EQ, {day}, {prev}, 1, 1, 1, 1, {close}, 1, 1000, 12.5, 10, {deliv}, {pct}
TCS, EQ, {day}, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -
"""


@pytest.mark.unit
def test_delivery_analysis(monkeypatch):
    frames = {
        date(2026, 9, 11): cash_market.parse_security_bhavdata(
            _SECURITY_BHAVDATA.format(day="11-Sep-2026", prev=100, close=104, deliv=700, pct=70.0).encode()),
        date(2026, 9, 10): cash_market.parse_security_bhavdata(
            _SECURITY_BHAVDATA.format(day="10-Sep-2026", prev=101, close=100, deliv=300, pct=30.0).encode()),
        date(2026, 9, 9): cash_market.parse_security_bhavdata(
            _SECURITY_BHAVDATA.format(day="09-Sep-2026", prev=100, close=101, deliv=500, pct=50.0).encode()),
    }
    monkeypatch.setattr(cash_market, "load_security_bhavdata", lambda day: frames.get(day))
    report = cash_market.delivery_analysis("RELIANCE", "2026-09-11", 3)
    assert "Window average delivery 50.00%" in report
    assert "1 up days vs 0 down days" in report
    assert "| 2026-09-11 | 104.00 | +4.00 |" in report
    assert "apply to NSE-listed companies only" in cash_market.delivery_analysis("NIFTY", "2026-09-11")


@pytest.mark.unit
def test_fii_dii_cash_flows_respects_analysis_date(monkeypatch):
    payload = [
        {"category": "DII", "date": "11-Sep-2026", "buyValue": "15109.58", "sellValue": "13141.41", "netValue": "1968.17"},
        {"category": "FII/FPI", "date": "11-Sep-2026", "buyValue": "12616.89", "sellValue": "13547.79", "netValue": "-930.9"},
    ]
    monkeypatch.setattr(cash_market, "nse_api_json", lambda path, params=None: payload)
    assert "| FII/FPI | 12,616.89 | 13,547.79 | -930.90 |" in cash_market.fii_dii_cash_flows("2026-09-11")
    assert "after the analysis date" in cash_market.fii_dii_cash_flows("2026-09-01")


@pytest.mark.unit
def test_index_fundamentals_history(monkeypatch):
    text = (
        "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
        "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
        "Nifty 50,11-09-2026,1,1,1,{close},1,0.5,1,1,{pe},3.5,1.3\n"
    )

    def fake_closes(day):
        pe = 22.0 if day >= date(2026, 9, 1) else 20.0
        frame = pd.read_csv(io.StringIO(text.format(close=23398.1, pe=pe)), dtype=str)
        return frame if day.weekday() < 5 else None

    monkeypatch.setattr(cash_market, "load_index_closes", fake_closes)
    report = cash_market.index_fundamentals("NIFTY26SEPFUT", "2026-09-11")
    assert "Nifty 50" in report
    assert "P/E is 22.00 versus 20.00 a year earlier (+10.0%)" in report
    with pytest.raises(fno.NoMarketDataError):
        cash_market.index_fundamentals("RELIANCE.NS", "2026-09-11")


@pytest.mark.unit
def test_fetch_archive_caches_files_and_final_misses(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    calls = []

    class Response:
        def __init__(self, status, content, ctype):
            self.status_code, self.content = status, content
            self.headers = {"content-type": ctype}

    class Session:
        def get(self, url, timeout=None):
            calls.append(url)
            if "missing" in url:
                return Response(404, b"<html>not found</html>", "text/html")
            return Response(200, b"a,b\n1,2\n", "text/csv")

    monkeypatch.setattr(nse_client, "_nse_session", lambda refresh=False: Session())
    old_day = date.today() - timedelta(days=30)
    assert nse_client.fetch_archive("https://x/ok.csv", group="g", name="ok.csv", trade_day=old_day) == b"a,b\n1,2\n"
    assert nse_client.fetch_archive("https://x/ok.csv", group="g", name="ok.csv", trade_day=old_day) == b"a,b\n1,2\n"
    assert nse_client.fetch_archive("https://x/missing.csv", group="g", name="m.csv", trade_day=old_day) is None
    assert nse_client.fetch_archive("https://x/missing.csv", group="g", name="m.csv", trade_day=old_day) is None
    assert len(calls) == 2  # both repeats served from the disk cache

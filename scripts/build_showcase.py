"""Publish aggregate reports and four-minute walkthroughs, never quote panels."""

from __future__ import annotations

import html
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from evidence import validate_verification
from publication import publish_site
from showcase_ui import write_explorer

ROOT = Path(__file__).resolve().parents[1]
CSS = """
:root{color-scheme:light;--ink:#152d3a;--muted:#58707e;--accent:#176e72;--line:#dae4e9}
*{box-sizing:border-box}body{margin:0;background:#eef3f4;color:var(--ink);font:16px/1.6 system-ui,'Segoe UI',sans-serif}
main{max-width:1120px;margin:38px auto;padding:38px;background:white;border-top:6px solid var(--accent);border-radius:8px}
.eyebrow{letter-spacing:.13em;text-transform:uppercase;color:var(--accent);font-size:12px;font-weight:750}
h1{font-size:clamp(28px,4vw,46px);line-height:1.15;letter-spacing:-.025em;margin:12px 0 22px}h2{line-height:1.25}h3{margin-bottom:8px}
p{max-width:88ch}a{color:#12696e;text-underline-offset:3px}small,.muted{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px;margin:18px 0}th,td{border-bottom:1px solid var(--line);padding:9px;text-align:left;overflow-wrap:anywhere}th{background:#eaf1f3}code{overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:26px 0}.card{border:1px solid var(--line);padding:24px;border-radius:8px;background:#fbfcfd}
.tag{display:inline-block;padding:4px 10px;background:#e2f0ef;color:#155d61;border-radius:4px;font-size:12px;font-weight:bold}
.metric{font-size:34px;font-weight:750;margin:12px 0 0}.links{display:flex;gap:16px;flex-wrap:wrap;margin-top:20px}
.note{border-left:4px solid #cc9455;background:#faf5ed;padding:16px 22px}.footer{border-top:1px solid var(--line);padding-top:20px;margin-top:30px;font-size:13px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);border-radius:5px;padding:8px 14px;background:white;color:var(--ink)}button.primary{background:var(--accent);color:white;border-color:var(--accent)}
.controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0}progress{width:100%;accent-color:var(--accent);height:8px}
.slide{min-height:550px;padding:8px 0 22px}.slide[hidden]{display:none}.slide img{max-width:100%;max-height:460px;object-fit:contain;background:white}li{margin:8px 0}
.top-nav{display:flex;gap:22px;flex-wrap:wrap;margin:0 0 30px;font-size:14px}.intro{font-size:19px;color:var(--muted)}
.panel{border-top:1px solid var(--line);margin:36px 0;padding-top:28px;scroll-margin-top:20px}.filters{display:flex;gap:18px;flex-wrap:wrap;margin:22px 0}.filters label{display:grid;gap:7px;font-size:13px;color:var(--muted)}
select{font:inherit;min-width:170px;max-width:100%;border:1px solid #b9cdd3;padding:10px 32px 10px 12px;border-radius:5px;background:#fff;color:var(--ink)}a:focus-visible,button:focus-visible,select:focus-visible{outline:3px solid #b57321;outline-offset:3px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;background:#eef5f5;padding:22px;border-radius:8px}.kpis strong{display:block;font-size:28px}.event-result strong{display:block;font-size:32px}.event-result{background:#eef5f5;padding:18px 22px;border-radius:6px}
.table-scroll{overflow:auto}.table-scroll table{min-width:620px}.bar-row{display:grid;grid-template-columns:45px 1fr 65px;gap:14px;align-items:center;font-size:13px;margin:9px 0}.bar-track{height:13px;background:#edf3f5;position:relative}.bar{height:100%;background:#176e72}.bar.development{background:#93bbc0}.reference{position:absolute;top:-3px;height:19px;border-left:2px solid #ab6b29}details{margin:22px 0}summary{cursor:pointer;color:#176e72;font-weight:650}.badge-warn{background:#fff0d8;color:#855b23}.card .finding{font-size:19px;line-height:1.45;font-weight:650}.primary-link{display:inline-block;background:var(--accent);color:white;padding:11px 20px;border-radius:5px;text-decoration:none}.evidence-callout{padding:26px;background:#eaf3f3;border-radius:8px;margin:28px 0}
@media(max-width:720px){main{margin:0;padding:22px;border-radius:0}.grid{grid-template-columns:1fr}.slide{min-height:450px}}
@media(max-width:600px){.kpis{grid-template-columns:1fr}.filters{display:grid;grid-template-columns:1fr}.filters select{width:100%}.top-nav{gap:14px}.metric{font-size:30px}.kpis strong{font-size:24px}}
@media print{main{margin:0;max-width:none}.controls,progress{display:none}.slide[hidden]{display:block}.slide{break-after:page}}
"""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def document(title: str, body: str, script: str = "", lang: str = "en") -> str:
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main>{script}</body></html>")


def copy_report(source: Path, destination: Path, names: tuple[str, ...]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        item = source / name
        if not item.is_file():
            raise FileNotFoundError(f"Required report artifact missing: {item}")
        shutil.copyfile(item, destination / name)
    for item in sorted((source / "figures").glob("*.png")):
        (destination / "figures").mkdir(exist_ok=True)
        shutil.copyfile(item, destination / "figures" / item.name)
    for name in ("annual.csv", "event_responses.csv", "event_series.csv", "currency_hpl.csv"):
        item = source / "data" / name
        if item.is_file():
            (destination / "data").mkdir(exist_ok=True)
            shutil.copyfile(item, destination / "data" / name)


def reading_page(path: Path, title: str, back: str = "../index.html") -> None:
    """Render the small, controlled Markdown vocabulary in our public handouts."""
    def inline(value: str) -> str:
        value = html.escape(value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", value)

    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = [f"<a href='{back}'>← Report gallery</a>"]
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("|"):
            rows = []
            headers = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if not re.fullmatch(r"[|\s:—-]+", row):
                    cells = [cell.strip() for cell in row.strip("|").split("|")]
                    if not headers:
                        headers = cells
                    else:
                        for i, cell in enumerate(cells):
                            if i < len(headers) and headers[i] in ("spread_coverage", "coverage", "equal_date_coverage"):
                                try:
                                    cells[i] = f"{float(cell):.2%}"
                                except ValueError:
                                    pass
                    labels = {"split": "Period", "group_status": "Daily quote group", "quotes": "Quotes",
                              "dates": "Dates", "spread_coverage": "Within bid/ask", "mae_points": "MAE (points)",
                              "rmse_points": "RMSE (points)", "development": "Jul–Aug development",
                              "temporal_test": "Sep–Dec evaluation", "PARITY_COMPATIBLE_DAILY_PROXY": "Parity-compatible proxy",
                              "EXPLORATORY_INCONSISTENT_QUOTES": "Exploratory inconsistent quotes"}
                    rows.append([inline(labels.get(cell, cell)) for cell in cells])
                index += 1
            blocks.append("<table>" + "".join("<tr>" + "".join(
                f"<{tag}>{cell}</{tag}>" for cell in row) + "</tr>"
                for i, row in enumerate(rows) for tag in ["th" if i == 0 else "td"]) + "</table>")
            continue
        if line.startswith("#"):
            depth = min(len(line) - len(line.lstrip("#")), 3)
            blocks.append(f"<h{depth}>{inline(line.lstrip('#').strip())}</h{depth}>")
        elif line:
            blocks.append(f"<p>{inline(line)}</p>")
        index += 1
    path.with_suffix(".html").write_text(document(title, "".join(blocks),
                                                lang="zh-CN" if "INTERVIEW_NOTES_ZH" in path.name else "en"), encoding="utf-8")


def tour(destination: Path, title: str, slides: list[tuple[str, str]], figures: list[str]) -> None:
    sections = []
    for index, (heading, text) in enumerate(slides):
        picture = (f"<img src='figures/{html.escape(figures[index])}' alt='{html.escape(heading)}'>"
                   if index < len(figures) and figures[index] else "")
        sections.append(f"<section class='slide' {'hidden' if index else ''}><p class='eyebrow'>"
                        f"{index + 1} / {len(slides)} · Research walkthrough</p><h2>{html.escape(heading)}</h2>"
                        f"<p>{html.escape(text)}</p>{picture}</section>")
    controls = ("<div class='controls'><button id='play' class='primary'>Start 4-minute walkthrough</button>"
                "<button id='prev'>Previous</button><button id='next'>Next</button>"
                "<span id='status' aria-live='polite'>Paused · 0:00 / 4:00</span></div>"
                "<progress id='progress' max='240' value='0' aria-label='Walkthrough progress'></progress>")
    script = """<script>
const slides=[...document.querySelectorAll('.slide')];let elapsed=0,playing=false;const length=240;
const play=document.getElementById('play'),status=document.getElementById('status'),progress=document.getElementById('progress');
function draw(){let current=Math.min(slides.length-1,Math.floor(elapsed/(length/slides.length)));slides.forEach((x,i)=>x.hidden=i!==current);progress.value=elapsed;status.textContent=(playing?'Playing':'Paused')+' · '+Math.floor(elapsed/60)+':'+String(elapsed%60).padStart(2,'0')+' / 4:00';play.textContent=playing?'Pause':elapsed>=length?'Replay':'Start / resume';}
play.onclick=()=>{if(elapsed>=length)elapsed=0;playing=!playing;draw();};
document.getElementById('prev').onclick=()=>{elapsed=Math.max(0,(Math.floor(elapsed/40)-1)*40);draw();};
document.getElementById('next').onclick=()=>{elapsed=Math.min(239,(Math.floor(elapsed/40)+1)*40);draw();};
document.addEventListener('keydown',e=>{if(e.key==='ArrowRight'){e.preventDefault();document.getElementById('next').click();}if(e.key==='ArrowLeft'){e.preventDefault();document.getElementById('prev').click();}});
setInterval(()=>{if(playing){elapsed++;if(elapsed>=length){elapsed=length;playing=false;}draw();}},1000);
draw();</script>"""
    body = (f"<a href='../index.html'>← Both projects</a><h1>{html.escape(title)}</h1>"
            "<p class='muted'>Six 40-second stops. Read the evidence at your own pace or use autoplay. "
            "This is a silent walkthrough, not a narrated video.</p>" + controls + "".join(sections) +
            "<div class='footer'><a href='report.html'>Open full validation report</a> · "
            "<a href='MANAGEMENT_SUMMARY.html'>Management summary</a> · "
            "<a href='DEMO_SCRIPT.html'>Speaking script</a> · "
            "<a href='INTERVIEW_NOTES_ZH.html'>中文面试提纲</a></div>")
    (destination / "demo.html").write_text(document(title, body, script), encoding="utf-8")
    lines = [f"# {title}: four-minute demonstration", "", "Six 40-second sections; pause for questions.", ""]
    for i, (heading, text) in enumerate(slides):
        lines.extend([f"## {i * 40 // 60}:{i * 40 % 60:02d} — {heading}", "", text, ""])
    (destination / "DEMO_SCRIPT.md").write_text("\n".join(lines), encoding="utf-8")


def build(output: Path) -> None:
    from market_risk.audit import load_audit_receipt
    from market_risk.reporting import load_report_receipt
    from market_risk.validation import load_validation_result
    from option_validation.report import load_report_receipt as load_option_report_receipt

    OUT = output
    tests_path = ROOT / "artifacts/verification/summary.json"
    tests = json.loads(tests_path.read_text(encoding="utf-8"))
    validate_verification(ROOT, tests)
    market = ROOT / "market-risk-validation/output/full-study"
    options = ROOT / "option-pricing-validation/output/full-study"
    load_option_report_receipt(options)
    risk, _ = load_validation_result(market / "validation.json", market / "predictions.csv")
    load_report_receipt(market / "report", market / "validation.json", market / "predictions.csv")
    risk_manifest = json.loads((market / "run_manifest.json").read_text(encoding="utf-8"))
    risk_diagnostics = json.loads((market / "validation.diagnostics.json").read_text(encoding="utf-8"))
    option_diagnostics = json.loads((options / "diagnostics.json").read_text(encoding="utf-8"))
    prices = json.loads((options / "results.json").read_text(encoding="utf-8"))
    price_validation = json.loads((options / "validation.json").read_text(encoding="utf-8"))
    price_receipt = json.loads((options / "validation_receipt.json").read_text(encoding="utf-8"))
    if price_receipt["validation_sha256"] != digest(options / "validation.json"):
        raise ValueError("Option validation changed after its integrity receipt")
    if price_validation["results_sha256"] != digest(options / "results.json"):
        raise ValueError("Option validation belongs to different results")
    for filename, expected in prices["files"].items():
        if digest(options / filename) != expected:
            raise ValueError(f"Option report input changed after validation: {filename}")
    intake = json.loads((options / "ingest_manifest.json").read_text(encoding="utf-8"))
    audit_path = ROOT / "market-risk-validation/output/validator-audit"
    load_audit_receipt(audit_path)
    audit = json.loads((audit_path / "audit.json").read_text(encoding="utf-8"))
    if audit["preset"] != "formal":
        raise ValueError("The published validator audit must use the formal preset")
    if price_validation["software_validation"] != "PASS":
        raise ValueError("Refusing to publish an options showcase with failed software validation")
    copy_report(market / "report", OUT / "market-risk", ("report.md", "report.html"))
    copy_report(options, OUT / "options", ("VALIDATION_REPORT.md", "MANAGEMENT_SUMMARY.md",
                                         "INTERVIEW_NOTES_ZH.md", "report.html", "validation.json"))
    for name in ("audit.md", "audit.json"):
        shutil.copyfile(audit_path / name, OUT / "market-risk" / name)
    selected = risk["development_selected_model"]
    models = risk["splits"]["test"]["models"]
    chosen = models[selected]
    dates = chosen["n"]
    option_test = next(row for row in prices["market"]["summaries"]
                       if row["split"] == "temporal_test" and row["rate_shift"] == 0
                       and row["group_status"] == "PARITY_COMPATIBLE_DAILY_PROXY"
                       and "moneyness_band" not in row)
    chf = next(event for event in risk_diagnostics["events"] if event["event_id"] == "chf_floor_2015")
    chf_fhs = next(row for row in chf["models"] if row["model"] == "ewma_fhs")
    paired_rates = [row for row in option_diagnostics["matched_rate"] if row["split"] == "temporal_test"
                    and row["base_group_status"] == "ALL_BASE_STATUSES"]
    paired_base = paired_rates[0]
    max_rate_effect = max(abs(row["delta_mae_points"]) for row in paired_rates)
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "market": {"development_selected_model": selected, "test_models": models,
                   "data_sha256": risk_manifest["source_sha256"],
                   "protocol_sha256": risk_manifest["protocol_sha256"],
                   "predictions_sha256": risk_manifest["predictions_sha256"],
                   "annual_diagnostics": risk_diagnostics["annual"]},
        "options": {"source_rows": intake["source_rows"], "accepted_rows": intake["accepted_rows"],
                    "excluded_rows": intake["excluded_rows"], "aggregate_market_results": prices["market"],
                    "software_validation": price_validation["software_validation"],
                    "market_validation": price_validation["market_validation"],
                    "numerical_cases_checked": price_validation.get("numerical_cases_checked"),
                    "market_checks": price_validation["market_checks"],
                    "results_sha256": price_validation["results_sha256"],
                    "descriptive_diagnostics": {key: option_diagnostics[key] for key in
                                                ("population", "matched_rate", "error_slices", "interpretations")}},
        "offline_verification": None if tests is None else {
            "status": tests["status"], "junit_totals": tests["junit_totals"],
            "python": tests["python"], "packages": tests["packages"], "platform": tests["platform"]},
        "publication": "Aggregate research only; raw/provider quote and derived contract panels remain local.",
        "synthetic_validator_audit": audit,
    }
    (OUT / "RESULTS.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    table = "\n".join(f"| {name} | {r['n']:,} | {r['var_99']['exceptions']} | {r['scores']['fz0_mean']:.4f} | {r['assessment']} |" for name, r in models.items())
    management = ("# Market risk: management summary\n\n"
        f"The development-selected method is **{selected}**. On **{dates:,} held-out observations**, its "
        f"assessment is **{chosen['assessment']}** after multiplicity adjustment. This is a research finding, not production approval.\n\n"
        "| Model | Held-out days | 99% exceptions | Mean FZ0 | Assessment |\n|---|---:|---:|---:|---|\n" + table + "\n\n"
        "The EUR 5m-initial cash book holds fixed quantities of five currencies. Quotes come from ECB and losses are hypothetical. "
        "Reference-rate observations omit transaction costs, funding and liquidity effects.\n\n"
        "Decision: review coverage, tail-loss magnitude and exception clustering together. An unlimited risk buffer is not a model improvement. "
        "A non-rejected test is not proof; sparse tails and regime changes limit inference. "
        "Any remediation should be documented as a new model version and evaluated on genuinely new evidence.\n\n"
        "The independent validator reads frozen forecasts, applies coverage/independence tests and a separate ES diagnostic, "
        "and retains proper scoring, uncertainty and stress periods. See the full report for hypotheses, provenance and limitations.\n")
    (OUT / "market-risk/MANAGEMENT_SUMMARY.md").write_text(management, encoding="utf-8")
    notes = ("# 市场风险项目：中文面试说明\n\n"
        f"开场：我用 ECB 的真实汇率，构造固定五币种现金组合。开发期选出 {selected}，"
        f"随后在 {dates:,} 个封存测试观察日上独立验证，结论是 {chosen['assessment']}。\n\n"
        "1. 先解释报价方向：ECB 是每 EUR 对应多少外币，外币现金的 EUR 价值要取倒数。\n"
        "2. 说明前视控制：每个预测只看到上一观察日，FHS 的历史残差也使用其当时已有的波动率。\n"
        "3. 区分 VaR 与 ES：超越次数正确不意味着尾部损失幅度正确。\n"
        "4. 解释验证器反例：尾部低估、连续超越、单独降低 ES 和无限放大风险，各应得到不同诊断。\n"
        "5. 承认边界：参考价不是成交价，统计未拒绝不是模型正确，历史数据也可能被修订。\n\n"
        f"可复核案例：2015-01-15 瑞郎事件，这个组合实际获得约 EUR {chf['signed_hpl_eur']:,.0f} 收益。"
        f"FHS 的 99% VaR 从事件前确定的 EUR {chf_fhs['anchor_var_99_eur']:,.0f} 升至次日 EUR {chf_fhs['next_var_99_eur']:,.0f}。"
        "解释为什么盈利冲击也会扩大风险估计，并明确次日预测已经知道当天冲击。年度分布和事件回放均为事后描述，不增加显著性结论。\n\n"
        "展示顺序：组合和单位 → 损益与VaR图 → 三模型比较 → 压力事件和验证发现 → 使用限制。\n")
    (OUT / "market-risk/INTERVIEW_NOTES_ZH.md").write_text(notes, encoding="utf-8")
    risk_slides = [
        ("A fixed book and a falsifiable question", "Can a plausible-looking risk forecast survive independent checks? Five foreign-currency cash positions start at EUR 1m equivalent each, then remain fixed. ECB observations are reference prices; the losses are hypothetical."),
        ("Only information available at the time", "Historical simulation, EWMA Gaussian and EWMA filtered historical simulation share the same book. Forecasts use prior observations. FHS standardizes historical returns using their own prior volatility, preventing a subtle form of look-ahead."),
        ("A proper score, not the fewest exceptions", f"Development selected {selected}. The final comparison uses {dates:,} held-out dates. Proper VaR–ES scoring penalizes underestimation and excessive buffers; exception counts alone cannot select a useful model."),
        ("A profitable shock can still raise measured risk", f"On the CHF event date, this long-currency book gained EUR {chf['signed_hpl_eur']:,.0f}. FHS 99% VaR rose from EUR {chf_fhs['anchor_var_99_eur']:,.0f} before the event to EUR {chf_fhs['next_var_99_eur']:,.0f} for the next observation. The later buffer used the observed shock; it was not an advance prediction. Annual diagnostics and event replay are descriptive additions, not new significance tests."),
        ("Test the validator itself", f"Across {audit['protocol']['repetitions']} simulated paths, the clustered-hit diagnostic rejected {audit['results']['clustered_hits']['independence_rejections_rate']:.0%}; isolated 20% ES underestimation was detected {audit['results']['es_only_20pct_low']['es_underestimation_rejections_rate']:.0%} of the time. Correct-normal ES false rejection was {audit['results']['normal_correct']['es_underestimation_rejections_rate']:.1%}. These estimates have uncertainty and describe these controls, not market performance."),
        ("A documented model-risk judgement", f"The selected model's held-out assessment is {chosen['assessment']}. Gaussian forecasts had {models['ewma_gaussian']['var_99']['exceptions']} 99% exceptions versus {dates * .01:.2f} expected, and were rejected despite a lower average FZ0 score. Calibration and scoring answer different questions. Any remediation needs a new version and new evidence."),
    ]
    tour(OUT / "market-risk", "Market risk validation", risk_slides,
         ["", "loss_and_var.png", "model_comparison.png", "event_responses.png", "", ""])
    option_slides = [
        ("Two different questions", "Does the pricing implementation calculate the assumed model correctly? Does that model explain observed quotes? Agreement with QuantLib answers the first question, not the second."),
        ("Analytic, numerical and reference checks", f"The frozen benchmark contains {price_validation.get('numerical_cases_checked', 0)} checked cases. Analytic prices and Greeks are compared with QuantLib, and independent CRR grids measure convergence. Boundary and invalid cases retain explicit states."),
        ("A free, imperfect market sample", f"The source has {intake['source_rows']:,} rows; {intake['accepted_rows']:,} meet the fixed product and data rules. Only European PM-settled SPXW options, 30–180 days, enter the study. Quote times are missing, so synchronization is not established."),
        ("Fit once, test different strikes", "Whole call/put strike groups are assigned to calibration or holdout. Training pairs determine the forward; one common volatility is fitted per date and expiry. Every prediction must remain bound to those fitted parameters. Replacing each holdout volatility by its inverted quote IV is explicitly rejected."),
        ("Model misspecification and input uncertainty", f"Among {option_test['quotes']:,} September–December held-out quotes in parity-compatible daily groups, common-volatility spread coverage is {option_test['spread_coverage']:.2%} and mean absolute error is {option_test['mae_points']:.2f} index points. Poor fit remains visible. Missing timestamps and the flat Treasury proxy prevent clean attribution of all error to the model. Per-contract IV is diagnostic, never held-out accuracy."),
        ("Compare the same quotes before attributing the error", f"On {paired_base['common_quotes']:,} fixed September–December held-out quotes across all base statuses, a ±100 bp discount scenario changes MAE by at most {max_rate_effect:.3f} points after training-only recalibration; baseline MAE is {paired_base['base_mae_points']:.2f}. Changing cohort composition can exaggerate apparent sensitivity. This is descriptive scenario evidence, not causal identification or proof that data uncertainty is immaterial."),
    ]
    tour(OUT / "options", "Index option pricing validation", option_slides,
         ["", "crr_convergence.png", "", "", "holdout_errors.png", "matched_rate_sensitivity.png"])
    cv = ("# Evidence-based CV bullets and interview pointers\n\n"
        "These claims describe the completed local study, not production deployment or trading performance. "
        "Adapt the wording to the role; retain the qualifications.\n\n"
        "## Market risk validation\n\n"
        f"- Built a reproducible EUR FX cash-book validation study using 6,913 ECB observations; "
        f"compared historical, EWMA Gaussian and filtered historical VaR/ES over {dates:,} held-out dates.\n"
        "- Implemented independent coverage, clustering and approximate ES diagnostics, proper VaR–ES scoring, "
        "stress analysis and a 200-path synthetic audit with uncertainty intervals; retained rejected models and data limitations.\n\n"
        "## European index option pricing validation\n\n"
        f"- Implemented analytic European option prices, Greeks, IV inversion and independent CRR convergence checks; "
        f"validated {price_validation.get('numerical_cases_checked', 0)} frozen benchmark cases against QuantLib.\n"
        f"- Screened {intake['source_rows']:,} vendor sample records to {intake['accepted_rows']:,} eligible SPXW quotes, "
        "calibrated common volatility on training strike groups and evaluated withheld strikes with explicit "
        "quote-synchronization and discount-proxy limitations.\n\n"
        "## 中文面试回答顺序\n\n"
        "先讲金融问题和单位约定，再展示一项可复核结果，最后解释影响与适用限制。"
        "市场风险应解释评分与覆盖率为何可能给出不同信息；期权应解释实现正确为何不等于市场拟合充分。"
        "用验证器反例说明你怎样发现错误，不把测试数量当作经济模型有效性的证明。\n")
    (OUT / "CV_BULLETS.md").write_text(cv, encoding="utf-8")
    for project in ("market-risk", "options"):
        for filename, title in (("MANAGEMENT_SUMMARY", "Management summary"),
                                ("INTERVIEW_NOTES_ZH", "中文面试提纲"), ("DEMO_SCRIPT", "Demonstration script")):
            reading_page(OUT / project / f"{filename}.md", title)
    reading_page(OUT / "market-risk/audit.md", "Synthetic validator audit")
    reading_page(OUT / "CV_BULLETS.md", "Evidence-based CV bullets", "index.html")
    write_explorer(OUT, document, risk_diagnostics, option_diagnostics)
    option_report = OUT / "options/report.html"
    option_report.write_text(option_report.read_text(encoding="utf-8").replace(
        'href="MANAGEMENT_SUMMARY.md"', 'href="MANAGEMENT_SUMMARY.html"'), encoding="utf-8")
    verification = "Verification not yet recorded" if tests is None else f"{tests['junit_totals']['tests']} tests · {tests['status']}"
    gaussian = models["ewma_gaussian"]
    labels = {"historical": "历史模拟", "ewma_gaussian": "EWMA 正态", "ewma_fhs": "过滤历史模拟"}
    assessments = {"rejected": "被拒绝", "not_rejected": "未被拒绝", "insufficient_evidence": "证据不足"}
    selected_statement = f"开发期选出的{labels[selected]}{assessments.get(chosen['assessment'], '需进一步审查')}"
    gaussian_statement = "正态模型覆盖率被拒绝" if gaussian["assessment"] == "rejected" else "平均评分与尾部覆盖分别判断"
    body = f"""<nav class='top-nav'><a href='evidence.html'>交互式证据</a><a href='#studies'>两项研究</a><a href='CV_BULLETS.html'>简历素材</a><a href='../README.md'>复现说明</a></nav>
<p class='eyebrow'>Market &amp; pricing model validation</p><h1>模型算得对，<br>还要看风险是否判断得对。</h1>
<p class='intro'>两项独立金融验证研究。从真实数据出发，保留模型失效的证据，说明结果可以支持什么判断。</p>
<div class='tag'>{html.escape(verification)} · 本地离线验收</div>
<div class='evidence-callout'><strong>先用两分钟，查看关键发现。</strong><p>按年份查看超越与风险缺口，重放瑞郎事件前后的信息变化，再用同一批期权报价比较利率情景。</p><a class='primary-link' href='evidence.html'>打开交互式证据 →</a></div>
<div class='grid' id='studies'>
<article class='card'><p class='eyebrow'>01 · Market risk</p><h2>外汇组合的尾部风险</h2>
<span class='tag badge-warn'>发现：{gaussian_statement}</span>
<div class='metric'>{gaussian['var_99']['exceptions']} <small>/ {dates * .01:.2f}</small></div><small>实际 99% VaR 超越次数 / 理论期望 · {dates:,} 个评估日</small>
<p class='finding'>平均评分较好，也可能低估尾部事件的发生频率。</p>
<p>比较历史模拟、EWMA 正态和过滤历史模拟。{selected_statement}；未拒绝不等于模型已被证明正确。</p>
<div class='links'><a href='market-risk/report.html'>完整验证报告</a><a href='market-risk/demo.html'>4 分钟演示</a><a href='market-risk/MANAGEMENT_SUMMARY.html'>管理摘要</a><a href='market-risk/INTERVIEW_NOTES_ZH.html'>面试提纲</a><a href='market-risk/audit.html'>验证器审计</a></div></article>
<article class='card'><p class='eyebrow'>02 · Pricing validation</p><h2>欧式指数期权定价</h2>
<span class='tag badge-warn'>发现：共同波动率的市场拟合不足</span>
<div class='metric'>{option_test['spread_coverage']:.2%}</div><small>落入买卖价差的比例 · {option_test['quotes']:,} 条留出报价</small>
<p class='finding'>公式与 QuantLib 一致，仍可能无法解释真实报价。</p>
<p>上述数字来自 9–12 月、基准利率下的平价兼容组。全研究保留 {intake['accepted_rows']:,} 条合格报价；缺少精确时间戳等限制贯穿分析。</p>
<div class='links'><a href='options/report.html'>完整验证报告</a><a href='options/demo.html'>4 分钟演示</a><a href='options/MANAGEMENT_SUMMARY.html'>管理摘要</a><a href='options/INTERVIEW_NOTES_ZH.html'>面试提纲</a></div></article></div>
<div class='note'><strong>结论的边界。</strong> ECB 参考价产生的是假设损益；期权日频报价未被证明同步。新增分年、事件与成对情景诊断属于事后描述，没有重新调参或新增显著性结论。</div>
<details><summary>方法与验收证据</summary><p>每个项目分别提供模型计算、独立验证与报告。正式模拟检查验证器的误拒率和检出能力；数据、代码及报告的校验记录用于发现不一致，并非数字签名。</p>
<div class='links'><a href='RESULTS.json'>汇总研究结果</a><a href='PUBLISH_MANIFEST.json'>报告文件校验</a><a href='../docs/ACCEPTANCE.md'>验收记录</a><a href='../docs/INDEPENDENT_REVIEW.md'>独立审查</a></div></details>
<div class='footer'>Sources: ECB reference rates · Federal Reserve H.15 via FRED · HistoricalData.net free sample.<br>计算与结论由本项目生成。原始期权行情保留在本地。</div>"""
    (OUT / "index.html").write_text(document("Market Model Validation Lab", body, lang="zh-CN"), encoding="utf-8")
    validate_verification(ROOT, tests)


def main() -> None:
    target = publish_site(ROOT, build)
    print(f"Complete gallery: {target / 'index.html'}; previous gallery retained in private publication history")


if __name__ == "__main__":
    main()

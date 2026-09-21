"""Standalone evidence-led Markdown and HTML reports from frozen artefacts."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from option_validation.data import sha256, write_json
from option_validation.diagnostics import generate_diagnostics
from option_validation.diagnostics_validation import checked_diagnostics, validate_diagnostics


def _label(column: str) -> str:
    labels = {"split": "Period", "group_status": "Parity status", "rate_shift": "Rate shift",
              "spread_coverage": "Inside bid/ask", "mae_points": "MAE (points)", "rmse_points": "RMSE (points)",
              "base_group_status": "Base parity status", "common_quotes": "Matched quotes", "common_groups": "Matched groups",
              "shifted_group_status": "Shifted parity status", "call_put": "Option type", "moneyness_band": "Strike / daily spot",
              "equal_date_mean_error_points": "Daily mean signed error (points)", "equal_date_mae_points": "Daily mean MAE (points)",
              "equal_group_mae_points": "Group mean MAE (points)", "equal_date_delta_mae_points": "Daily mean change in MAE (points)",
              "equal_group_delta_mae_points": "Group mean change in MAE (points)", "delta_mae_points": "Quote mean change in MAE (points)",
              "equal_date_delta_coverage_pp": "Daily mean coverage change (pp)", "delta_coverage_pp": "Quote mean coverage change (pp)",
              "coverage": "Inside bid/ask", "equal_date_coverage": "Daily mean inside bid/ask"}
    return labels.get(column, column.replace("_", " ").capitalize())


def _cell(value, column: str) -> str:
    if isinstance(value, (float, int)):
        if column == "rate_shift":
            return f"{value * 10000:+.0f} bp"
        if column == "coverage" or column.endswith("_coverage"):
            return f"{value * 100:.2f}%"
        if isinstance(value, float):
            return f"{value:.5g}"
    names = {"development": "Jul–Aug", "temporal_test": "Sep–Dec",
             "PARITY_COMPATIBLE_DAILY_PROXY": "Compatible daily proxy",
             "EXPLORATORY_INCONSISTENT_QUOTES": "Exploratory inconsistent"}
    return names.get(str(value), str(value)).replace("|", "/").replace("\n", " ")


def _table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "No eligible observations; no market result is imputed."
    return "\n".join(["| " + " | ".join(_label(col) for col in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"] + ["| " + " | ".join(_cell(row.get(col, ""), col) for col in columns) + " |" for row in rows])


def _figures(output: Path, results: dict, validation: dict, pred: pd.DataFrame) -> list[tuple[str, str]]:
    folder = output / "figures"
    folder.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 125, "savefig.facecolor": "white"})
    figures = []
    convergence = {}
    convergence_ids = {case["case_id"] for case in results["numerical"] if case["crr_gate"]}
    for case in validation["numerical_checks"]:
        if case["case_id"] not in convergence_ids:
            continue
        for value in case["crr_errors"]:
            if value["steps"] in (128, 256, 512, 1024, 2048) and value["absolute_error"] is not None:
                convergence.setdefault(value["steps"], []).append(value["absolute_error"])
    if convergence:
        steps = sorted(convergence)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.loglog(steps, [max(np.mean(convergence[n]), 1e-15) for n in steps], "o-", label="Mean absolute error")
        ax.loglog(steps, [max(max(convergence[n]), 1e-15) for n in steps], "s--", label="Maximum absolute error")
        ax.set(xlabel="CRR steps", ylabel="Absolute price error, index points", title="Independent CRR versus QuantLib analytic price")
        ax.legend()
        fig.tight_layout()
        fig.savefig(folder / "crr_convergence.png")
        plt.close(fig)
        figures.append(("CRR convergence", "figures/crr_convergence.png"))
    if not pred.empty:
        held = pred[(pred["assignment"] == "holdout") & np.isclose(pred["rate_shift"], 0)].copy()
        if not held.empty:
            # Deterministic display thinning does not affect the full-sample metrics.
            shown = held.iloc[::max(1, len(held) // 4000)]
            fig, ax = plt.subplots(figsize=(8, 4.4))
            for split, frame in shown.groupby("split"):
                ax.scatter(frame["moneyness"], frame["error"], s=8, alpha=0.35, label=split)
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set(xlabel="Strike / observed daily underlying close", ylabel="Model minus quote midpoint, index points",
                   title="Held-out strikes: constant volatility fit; daily quote proxies")
            ax.legend()
            fig.tight_layout()
            fig.savefig(folder / "holdout_errors.png")
            plt.close(fig)
            figures.append(("Held-out price errors", "figures/holdout_errors.png"))
            group = held.groupby(["quote_date", "expiration"], sort=True).size().sort_values(ascending=False, kind="stable").index[0]
            surface = pred[(pred["quote_date"] == group[0]) & (pred["expiration"] == group[1]) & np.isclose(pred["rate_shift"], 0)]
            fig, ax = plt.subplots(figsize=(8, 4.4))
            for kind, frame in surface.groupby("kind"):
                frame = frame.dropna(subset=["iv_bid", "iv_ask"]).sort_values("strike")
                ax.vlines(frame["strike"], frame["iv_bid"] * 100, frame["iv_ask"] * 100, alpha=0.6,
                          color="#376faf" if kind == "call" else "#d47928", label=f"{kind}: bid/ask IV interval")
            ax.axhline(surface["sigma"].iloc[0] * 100, color="black", linestyle="--", label="Common sigma fitted on training strikes")
            ax.set(xlabel="Strike", ylabel="Annual volatility, %", title=f"Diagnostic IV intervals: {group[0]}, expiry {group[1]}")
            ax.legend(fontsize=8)
            fig.tight_layout()
            fig.savefig(folder / "iv_intervals.png")
            plt.close(fig)
            figures.append(("Quote IV intervals are diagnostics, not held-out predictions", "figures/iv_intervals.png"))
    shock = pd.DataFrame(results["shocks"]["scenarios"])
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(shock["full_revaluation_pnl"], shock["greek_approximation_pnl"], c=shock["spot_change_pct"], cmap="coolwarm")
    low = min(shock["full_revaluation_pnl"].min(), shock["greek_approximation_pnl"].min())
    high = max(shock["full_revaluation_pnl"].max(), shock["greek_approximation_pnl"].max())
    ax.plot([low, high], [low, high], "k--", linewidth=1)
    ax.set(xlabel="Full revaluation P&L", ylabel="Delta/gamma/vega/theta approximation", title="Synthetic four-leg portfolio, multiplier 100")
    fig.tight_layout()
    fig.savefig(folder / "shock_approximation.png")
    plt.close(fig)
    figures.append(("Synthetic portfolio shocks", "figures/shock_approximation.png"))
    return figures


def _checked_snapshot(output: Path) -> tuple[dict, dict]:
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    validation = json.loads((output / "validation.json").read_text(encoding="utf-8"))
    receipt = json.loads((output / "validation_receipt.json").read_text(encoding="utf-8"))
    if receipt["validation_sha256"] != sha256(output / "validation.json"):
        raise ValueError("Validation assessment changed since its integrity receipt")
    if set(receipt.get("source_hashes", {})) != {"validation.py", "market_validation.py"}:
        raise ValueError("Validator source receipt is missing; rerun validate")
    for name, digest in receipt["source_hashes"].items():
        if sha256(Path(__file__).with_name(name)) != digest:
            raise ValueError("Validator source changed; rerun validate before reporting")
    if validation["results_sha256"] != sha256(output / "results.json") or receipt.get("results_sha256") != validation["results_sha256"]:
        raise ValueError("Validation is stale; rerun validate before writing the report")
    for filename, digest in results["files"].items():
        if not (output / filename).exists() or sha256(output / filename) != digest:
            raise ValueError(f"Frozen artefact changed since validation: {filename}")
    return results, validation


def _write_report_receipt(output: Path, artifact_names: list[str], diagnostics_status: str) -> None:
    bound_files = ["validation.json", "validation_receipt.json", "results.json"]
    if diagnostics_status == "PASS":
        bound_files += ["diagnostics.json", "diagnostics_validation.json", "diagnostics_validation_receipt.json"]
    write_json(output / "report_receipt.json", dict(schema_version=1, diagnostics_status=diagnostics_status,
        **{name.removesuffix(".json") + "_sha256": sha256(output / name) for name in bound_files},
        report_source_sha256=sha256(Path(__file__)),
        source_hashes={name: sha256(Path(__file__).with_name(name)) for name in ("report.py", "diagnostics.py", "diagnostics_validation.py")},
        artifacts={name: sha256(output / name) for name in artifact_names},
        note="Integrity consistency receipt, not a signature or adversarial security boundary."))


def load_report_receipt(output: Path) -> dict:
    """Return a fully checked report receipt for publication, or refuse stale evidence."""
    output = Path(output)
    receipt = json.loads((output / "report_receipt.json").read_text(encoding="utf-8"))
    _, assessment = _checked_snapshot(output)
    sources = {"report.py", "diagnostics.py", "diagnostics_validation.py"}
    if set(receipt.get("source_hashes", {})) != sources:
        raise ValueError("Report source receipt is incomplete; rerun report")
    for name, digest in receipt["source_hashes"].items():
        if sha256(Path(__file__).with_name(name)) != digest:
            raise ValueError("Report source changed; rerun report")
    if receipt.get("report_source_sha256") != sha256(Path(__file__)):
        raise ValueError("Report source binding changed; rerun report")
    bound_files = ["validation.json", "validation_receipt.json", "results.json"]
    if assessment["software_validation"] == "PASS":
        if receipt.get("diagnostics_status") != "PASS":
            raise ValueError("Successful report is missing audited descriptive diagnostics")
        checked_diagnostics(output)
        bound_files += ["diagnostics.json", "diagnostics_validation.json", "diagnostics_validation_receipt.json"]
    elif receipt.get("diagnostics_status") != "NOT_PERFORMED_SOFTWARE_FAILURE":
        raise ValueError("Failed software audit cannot support market diagnostics")
    for name in bound_files:
        if receipt.get(name.removesuffix(".json") + "_sha256") != sha256(output / name):
            raise ValueError(f"Report is stale relative to {name}; rerun report")
    page = (output / "report.html").read_text(encoding="utf-8")
    expected_artifacts = {"VALIDATION_REPORT.md", "MANAGEMENT_SUMMARY.md", "INTERVIEW_NOTES_ZH.md", "report.html"}
    expected_artifacts.update(re.findall(r'<img src="([^"]+)"', page))
    if set(receipt.get("artifacts", {})) != expected_artifacts:
        raise ValueError("Report artifact inventory is incomplete")
    for name, digest in receipt["artifacts"].items():
        path = (output / name).resolve()
        if not path.is_relative_to(output.resolve()) or not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Report artifact changed: {name}")
    return receipt


def _failure_report(output: Path, validation: dict) -> dict:
    """Preserve negative numerical findings without analysing unverified prices."""
    markdown = ("# European index option pricing — independent validation\n\n"
                "**Software validation: FAIL. Market acceptance: not established.**\n\n"
                "Post-hoc market diagnostics: **NOT PERFORMED — software audit failed**. "
                "Reported prices and market summaries must not support economic conclusions until these findings are resolved.\n\n"
                "## Independent validation failures\n\n" + _table(validation["failures"], ["check", "item", "error", "detail"]) + "\n\n"
                f"Results SHA-256: `{validation['results_sha256']}`. Complete failure details are retained in `validation.json`.\n")
    for name in ("VALIDATION_REPORT.md", "MANAGEMENT_SUMMARY.md"):
        (output / name).write_text(markdown, encoding="utf-8")
    (output / "INTERVIEW_NOTES_ZH.md").write_text("# 验证未通过\n\n数值或数据审计存在未解决问题，不能使用这些结果讨论模型适用性。事后市场诊断未执行。\n\n" + markdown, encoding="utf-8")
    (output / "report.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Option validation: FAIL</title><main><pre style="white-space:pre-wrap">' + html.escape(markdown) + "</pre></main></html>", encoding="utf-8")
    _write_report_receipt(output, ["VALIDATION_REPORT.md", "MANAGEMENT_SUMMARY.md", "INTERVIEW_NOTES_ZH.md", "report.html"], "NOT_PERFORMED_SOFTWARE_FAILURE")
    return dict(report=str(output / "report.html"), markdown=str(output / "VALIDATION_REPORT.md"), figures=0)


def report(output: Path) -> dict:
    results, validation = _checked_snapshot(output)
    if validation["software_validation"] != "PASS":
        return _failure_report(output, validation)
    if not (output / "diagnostics.json").exists():
        generate_diagnostics(output)
        validate_diagnostics(output)
    diagnostics = checked_diagnostics(output)
    chunks = []
    for chunk in pd.read_csv(output / "predictions.csv", chunksize=40000):
        selected = chunk[np.isclose(chunk["rate_shift"], 0)]
        if not selected.empty:
            chunks.append(selected)
    pred = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    groups = json.loads((output / "groups.json").read_text(encoding="utf-8"))["groups"]
    figures = _figures(output, results, validation, pred)
    figures.extend(_diagnostic_figures(output, diagnostics))
    ingest = json.loads((output / "ingest_manifest.json").read_text(encoding="utf-8")) if (output / "ingest_manifest.json").exists() else None
    summaries = [r for r in results["market"]["summaries"] if "moneyness_band" not in r]
    base = [r for r in summaries if r["rate_shift"] == 0]
    columns = ["split", "group_status", "quotes", "dates", "spread_coverage", "mae_points", "rmse_points"]
    rejected = {}
    for group in groups:
        if group["rate_shift"] == 0 and group["status"] == "REJECTED":
            rejected[group["reason"]] = rejected.get(group["reason"], 0) + 1
    max_error = max((r["absolute_error"] for r in validation["numerical_checks"]), default=0)
    lines = ["# European index option pricing — independent validation", "",
             f"**Software validation: {validation['software_validation']}. Market reliability: not established.**", "",
             "This study separates external numerical agreement from the suitability of constant-volatility pricing on a limited historical quote slice. No acceptance claim is made for a trading or production pricing model.", "",
             "Protocol chronology: rules were specified in implementation before the first full historical execution; this document was consolidated afterwards and validator/report defects were corrected after inspection. September–December is a retrospective fixed-protocol evaluation, not a freshly untouched prospective holdout.", "",
             "## Executive findings", "",
             f"- Frozen numerical cases checked: {len(validation['numerical_checks'])}; maximum analytic price difference from QuantLib: {max_error:.3g} index points.",
             f"- Independent validation failures: {len(validation['failures'])}. Full evidence is in `validation.json`; no failure is removed from the report.",
             f"- Base-rate date/expiry groups: {results['market']['base_groups']}; statuses: {results['market']['group_status_counts']}.",
             "- Parity-compatible daily quotes remain daily proxies. Inconsistent groups retain explicitly exploratory forward estimates and are reported separately.",
             "- A single implied volatility per contract is an inverse price diagnostic. Only a common volatility fitted on training strikes is evaluated on held-out strikes.", "",
             "## Scope, data and information boundaries", "",
             "SPXW European PM-settled vanilla calls/puts, 30–180 calendar days, K/S in [0.8, 1.2], positive bid, uncrossed quotes, relative spread at most 15%. Quote-time absence and asynchronous closing snapshots are explicit limitations. ACT/365F date differences approximate end-of-day maturity time.", "",
             "July–August 2022 is development; September–December is the frozen temporal-protocol test. Each date/expiry still recalibrates using its contemporaneous training strikes. This is a cross-strike fit assessment, not a future-price forecast. The SHA-256 assignment keeps each strike's call and put together (70% train buckets / 30% holdout buckets).", "",
             "Discounting uses the latest strictly prior-date DGS3MO observation, at most seven calendar days old. This historical 3-month Treasury rate is a flat discount proxy, not an OIS or zero-coupon curve. Forward and common volatility are reconstructed from training quotes for each of base, −100 bp and +100 bp rate assumptions.", ""]
    if ingest:
        lines.extend([f"Source rows: {ingest['source_rows']:,}; rows surviving predeclared eligibility: {ingest['accepted_rows']:,}; excluded: {ingest['excluded_rows']:,}. `ingest_exclusions.csv` records every rejected row and reason; `groups.json` records every calibration rejection and parity conflict.", ""])
    lines.extend(["## Numerical validation and approximation risk", "",
                  "BSM analytic prices and spot Greeks are compared with QuantLib AnalyticEuropeanEngine on fixed complete-input cases. CRR independently sums binomial terminal payoffs at 128–2048 steps. Both numerical engines share lognormal-model assumptions; agreement does not validate those economic assumptions. Price, delta, gamma, vega, theta and rho units and tolerances are frozen in `PROTOCOL.md`.", "",
                  "Expired/zero-volatility payoffs have explicit deterministic limits and nonregular Greek statuses. IV inversion rejects impossible prices and flags low-vega conditioning. The synthetic four-leg shock experiment measures approximation error against full revaluation, independently recomputed with QuantLib; it is not a historical hedging backtest.", "",
                  "## Held-out quote findings", "", _table(base, columns), "",
                  "Coverage is the fraction of held-out model prices inside the observed bid/ask interval. Observations cluster by date and expiry; raw counts are not independent sample sizes. No minimum coverage target is retrofitted to the observations.", "",
                  "### Discount-proxy sensitivity (forward and volatility refitted on training strikes)", "",
                  "The next legacy table groups each rate scenario by its own parity status. Membership can change across rows; subtracting its MAE values is not a matched rate effect. It is retained as a composition description. The fixed-cohort post-hoc comparison follows below.", "",
                  _table(summaries, ["split", "group_status", "rate_shift", "quotes", "spread_coverage", "mae_points"]), "",
                  "### Calibration rejections", "", _table([dict(reason=k, groups=v) for k, v in sorted(rejected.items())], ["reason", "groups"]) if rejected else "No groups rejected by the calibration eligibility rules; exploratory inconsistency statuses are retained separately.", "",
                  "## Limitations, findings and recommendations", ""])
    paired_summary = [r for r in diagnostics["matched_rate"] if r["base_group_status"] == "ALL_BASE_STATUSES"]
    diagnostics_overall = [r for r in diagnostics["error_slices"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["call_put"] == "all" and r["moneyness_band"] == "all"]
    changed_statuses = [r for r in diagnostics["status_transitions"] if r["base_group_status"] != r["shifted_group_status"]]
    test_slices = [r for r in diagnostics["error_slices"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["split"] == "temporal_test" and r["call_put"] != "all" and r["moneyness_band"] != "all"]
    diagnostic_text = ["## Post-hoc descriptive diagnostics", "",
        "These diagnostics were selected after reviewing the original results. They preserve every original model, cleaning rule, fitted parameter and prediction. No p-values, confidence intervals, new holdout or tuning claim is added.", "",
        f"The paired rate cohort has {diagnostics['population']['common_quotes']:,} exact held-out quote IDs across {diagnostics['population']['common_groups']:,} date/expiry groups and {diagnostics['population']['common_dates']} dates. Excluded base quotes missing a scenario: {diagnostics['population']['excluded_base_quotes']}. Each comparison uses these same IDs and fixed **base-rate** status strata; changed alternative statuses are reported as outcomes.", "",
        "### Matched rate changes on a fixed cohort", "",
        _table(paired_summary, ["split", "rate_shift", "common_quotes", "common_groups", "delta_mae_points", "equal_date_delta_mae_points", "equal_group_delta_mae_points", "delta_coverage_pp", "equal_date_delta_coverage_pp"]), "",
        "A delta is shifted minus base. Forward and common volatility were refitted on training strikes in each original rate scenario. These are differences between full recalibrated assumptions, not partial rho and not causal interest-rate effects. The JSON also contains fixed baseline-status strata, status transitions and a per-date paired table.", "",
        "Only changed status memberships are listed below; they remain in the matched analysis under their base status. Counts are date/expiry groups, not independent samples.", "",
        _table(changed_statuses, ["split", "rate_shift", "base_group_status", "shifted_group_status", "groups", "quotes"]) if changed_statuses else "No parity-status transitions in this sample.", "",
        "### How observation weighting changes the descriptive result", "",
        _table(diagnostics_overall, ["split", "quotes", "dates", "groups", "mae_points", "equal_date_mae_points", "equal_group_mae_points", "coverage", "equal_date_coverage"]), "",
        "Quote-weighted means give more influence to dates with more quotes. Equal-date means first aggregate each date; equal-group means first aggregate each date/expiry. These are different descriptive estimands and do not make correlated quotes independent. Call/put × moneyness slices and daily series show where signed pricing errors concentrate without treating every quote as an independent trial.", "",
        "### September–December call/put and strike patterns", "",
        _table(test_slices, ["call_put", "moneyness_band", "quotes", "dates", "equal_date_mean_error_points", "equal_date_mae_points", "equal_date_coverage"]), "",
        "Positive signed error means model above quote midpoint. A repeated change in error sign across strikes is compatible with a constant-volatility specification missing market skew. This descriptive pattern does not isolate model dynamics from asynchronous quotes, forward reconstruction or discount-proxy errors. The near-spot band is K/S-based, not a forward-delta bucket; call/put slices can have different quote membership after the unchanged eligibility rules.", ""]
    insert_at = lines.index("## Limitations, findings and recommendations")
    lines[insert_at:insert_at] = diagnostic_text
    lines.extend([f"- {item}" for item in results["limitations"]])
    lines.extend(["- Treat Treasury-proxy and timestamp uncertainty as model-input risk; do not present exploratory parity reconciliation as a verified market calibration.",
                  "- Constant volatility may fit some strikes poorly even when the pricing code is correct. Preserve the negative evidence and bid/ask uncertainty before considering richer dynamics.",
                  "- Heston, a live market surface, American exercise, transaction-cost hedging, and derivative VaR integration are outside this study.", "",
                  "## Independent validation failures", "", _table(validation["failures"][:30], ["check", "item", "error", "detail"]) if validation["failures"] else "No unresolved automated validation findings.", "",
                  "## Figures", ""])
    for title, path in figures:
        lines.extend([f"### {title}", "", f"![{title}]({path})", ""])
    lines.extend(["## Reproduction and immutable evidence", "",
                  "Run `option-validation ingest`, `run`, `validate`, `diagnose`, then `report` with the same `--output` directory. The validator reads frozen outputs, verifies file hashes, uses QuantLib independently, audits rate availability and paired train/holdout membership, and reconstructs training forwards/objectives. Provider IV and Greeks are never an oracle.", "",
                  f"Results SHA-256: `{validation['results_sha256']}`. QuantLib version: `{validation.get('quantlib_version', 'unavailable')}`. Detailed predictions, exclusions, parameter choices, and failures remain beside this report.", ""])
    markdown = "\n".join(lines)
    (output / "VALIDATION_REPORT.md").write_text(markdown, encoding="utf-8")
    summary = ("# Management summary\n\n"
               f"Software validation: **{validation['software_validation']}**, based on {len(validation['numerical_checks'])} frozen cases and an external QuantLib implementation. "
               f"There are {len(validation['failures'])} unresolved automated findings.\n\n"
               "Market model acceptance is **not established**. The limited SPXW daily quote study evaluates one volatility per date/expiry on held-out strikes; it does not demonstrate a live pricing service or future trading performance.\n\n"
               "This is a retrospective fixed-protocol experiment. The protocol was consolidated into documentation and audit defects were corrected after the first complete execution; no fresh prospective holdout is claimed.\n\n"
               + _table(base, columns) + "\n\n"
               "## Post-hoc fixed-cohort sensitivity\n\n"
               + _table(paired_summary, ["split", "rate_shift", "common_quotes", "equal_date_delta_mae_points", "equal_date_delta_coverage_pp"]) + "\n\n"
               "These paired differences hold quote membership and baseline strata fixed. They include training-parameter refits; they are descriptive, not causal rho. Original scenario-specific parity tables have changing composition and cannot supply this comparison.\n\n"
               "Decision: use the package as a reproducible model-validation research case. Separate implementation correctness, discretisation error, input uncertainty and constant-volatility model risk. Timestamp uncertainty, Treasury discount proxies and inconsistent parity intervals prevent a claim of validated market calibration.\n")
    (output / "MANAGEMENT_SUMMARY.md").write_text(summary, encoding="utf-8")
    interview = ("# 面试讲解：欧式指数期权定价验证\n\n"
                 f"我把问题拆成数值实现、模型输入、模型适用性三层。独立 QuantLib 校验了 {len(validation['numerical_checks'])} 个冻结案例，结果 {validation['software_validation']}；这只能证明共享假设下的实现一致性，不能证明市场模型正确。\n\n"
                 "自写 BSM 与独立 CRR，展示步数收敛、边界处理和 Greeks 单位。IV 反解后重定价不是预测成绩；真实报价只把训练 strike 拟合的同一波动率拿去检验留出 strike，call/put 成对划分。\n\n"
                 "7–8 月开发、9–12 月遵循冻结协议，但每个测试日仍用当日训练 strike 校准；这是跨行权价验证，不能说预测未来。F 只来自训练 call/put 平价；历史三个月 Treasury 是折现代理，不能叫 OIS 曲线。±100 bp 下重新拟合训练参数做敏感性。\n\n"
                 "筛选与划分规则先写在实现中，文档在完整执行后整理，审查中又修复了验证器缺口；应称回顾性固定协议评估，不声称这是从未查看过的新测试集。\n\n"
                 "有平价交集的日收盘报价仍非同步报价证明；无交集但可稳定估计的组标为探索性、不隐藏负结果。Greeks 在完整合成输入上做 spot 验证；市场 forward Greeks 不伪装真实 spot Greeks。\n\n"
                 + "真实留出结果：\n\n" + _table(base, columns) + "\n\n"
                 + "事后补充的利率敏感性：原表按每个利率场景自己的平价状态分组，组成员会变，不能直接相减。我固定三种场景共同的报价ID，并用基准利率状态固定分层，再逐条配对计算差异；同时给每日期/到期组等权结果。它们是不同权重的描述统计，不能把相关报价当独立样本。F和sigma均重拟合，所以不是偏导rho，也不是因果效应。\n\n"
                 + _table(paired_summary, ["split", "rate_shift", "common_quotes", "equal_date_delta_mae_points", "equal_date_delta_coverage_pp"]) + "\n\n"
                 "没有承诺 Heston、实时曲面、交易收益、真实对冲 P&L 或投产。最有价值的讨论是何时应拒绝输入、为何代码正确仍会报价不匹配、下一步需要哪些更可靠的数据。\n")
    (output / "INTERVIEW_NOTES_ZH.md").write_text(interview, encoding="utf-8")
    # Standalone static HTML uses a readable preformatted report plus native tables/charts.
    tables = pd.DataFrame([{_label(col): _cell(row.get(col, ""), col) for col in columns} for row in base]).to_html(index=False, escape=True) if base else "<p>No eligible market observations.</p>"
    images = "".join(f'<figure><img src="{path}" alt="{html.escape(title)}"><figcaption>{html.escape(title)}</figcaption></figure>' for title, path in figures)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Option Model Validation</title><style>
body{{font:16px/1.6 system-ui,sans-serif;color:#15283b;background:#edf1f5;margin:0}}main{{max-width:1120px;margin:40px auto;background:white;padding:40px;border-radius:12px}}h1{{font-size:32px}}.status{{padding:16px;background:#e7eef4;border-left:5px solid #346582}}table{{border-collapse:collapse;font-size:13px;display:block;overflow:auto}}td,th{{border:1px solid #d4dde5;padding:8px;text-align:left}}img{{width:100%;max-width:920px}}figure{{margin:28px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 system-ui,sans-serif}}@media(max-width:700px){{main{{padding:18px;margin:8px}}}}</style><main><h1>European Index Option Validation</h1><p class="status">Software validation: <strong>{html.escape(validation['software_validation'])}</strong> · Market acceptance: <strong>not established</strong></p><p>External numerical agreement, quote uncertainty and model suitability are separate findings.</p><h2>Held-out quote results</h2>{tables}{images}<details open><summary>Complete validation report and boundaries</summary><pre>{html.escape(markdown)}</pre></details><p><a href="VALIDATION_REPORT.md">Markdown report</a> · <a href="MANAGEMENT_SUMMARY.md">Management summary</a> · <a href="validation.json">Machine-readable validation</a></p></main></html>'''
    (output / "report.html").write_text(page, encoding="utf-8")
    artifact_names = ["VALIDATION_REPORT.md", "MANAGEMENT_SUMMARY.md", "INTERVIEW_NOTES_ZH.md", "report.html", *[path for _, path in figures]]
    _write_report_receipt(output, artifact_names, "PASS")
    return dict(report=str(output / "report.html"), markdown=str(output / "VALIDATION_REPORT.md"), figures=len(figures))


def _diagnostic_figures(output: Path, diagnostics: dict) -> list[tuple[str, str]]:
    folder = output / "figures"
    figures = []
    paired = [row for row in diagnostics["matched_rate"] if row["base_group_status"] == "ALL_BASE_STATUSES"]
    if paired:
        paired.sort(key=lambda r: (r["split"], r["rate_shift"]))
        labels = [f"{'Jul–Aug' if r['split'] == 'development' else 'Sep–Dec'}\n{r['rate_shift'] * 10000:+.0f} bp" for r in paired]
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.6))
        for ax, metric, title in ((axes[0], "equal_date_delta_mae_points", "Change in MAE, index points"),
                                  (axes[1], "equal_date_delta_coverage_pp", "Change in spread coverage, percentage points")):
            ax.bar(np.arange(len(paired)), [r[metric] for r in paired], color=["#376faf" if r["rate_shift"] < 0 else "#d47928" for r in paired])
            ax.axhline(0, color="black", linewidth=.8)
            ax.set_xticks(np.arange(len(paired)), labels)
            ax.set_title(title, fontsize=11)
        fig.suptitle("Post-hoc: paired rate scenarios, fixed quote cohort, equal-date means", fontsize=12)
        fig.tight_layout()
        fig.savefig(folder / "matched_rate_sensitivity.png")
        plt.close(fig)
        figures.append(("Post-hoc matched rate sensitivity; refitted F and sigma, no causal claim", "figures/matched_rate_sensitivity.png"))
    daily = pd.DataFrame([r for r in diagnostics["daily_base"] if r["base_group_status"] == "ALL_BASE_STATUSES"])
    if not daily.empty:
        daily = daily.sort_values("quote_date")
        dates = pd.to_datetime(daily["quote_date"])
        fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
        axes[0].plot(dates, daily["mae_points"], color="#376faf")
        axes[1].plot(dates, daily["coverage"] * 100, color="#d47928")
        axes[0].set(ylabel="Daily MAE, index points", title="Post-hoc: date-level constant-volatility fit (all base statuses)")
        axes[1].set(ylabel="Inside bid/ask, %", xlabel="Quote date; series are descriptive, not independent observations")
        for ax in axes:
            ax.axvline(pd.Timestamp("2022-09-01"), color="gray", linestyle="--", linewidth=.8)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(folder / "daily_fit_diagnostics.png")
        plt.close(fig)
        figures.append(("Post-hoc daily fit diagnostics; no IID confidence interval", "figures/daily_fit_diagnostics.png"))
    slices = [r for r in diagnostics["error_slices"] if r["base_group_status"] == "ALL_BASE_STATUSES" and r["call_put"] != "all" and r["moneyness_band"] != "all"]
    if slices:
        splits = sorted({r["split"] for r in slices})
        fig, axes = plt.subplots(1, len(splits), figsize=(5 * len(splits), 4), squeeze=False)
        limit = max(abs(r["equal_date_mean_error_points"]) for r in slices) or 1
        bands = ["K/S<=0.95", "0.95<K/S<=1.05", "K/S>1.05"]
        for ax, split in zip(axes[0], splits, strict=True):
            values = np.full((2, 3), np.nan)
            for row in slices:
                if row["split"] == split:
                    values[["call", "put"].index(row["call_put"]), bands.index(row["moneyness_band"])] = row["equal_date_mean_error_points"]
            ax.imshow(values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
            ax.set_xticks(range(3), ["K/S ≤ .95", ".95 < K/S ≤ 1.05", "K/S > 1.05"], fontsize=9)
            ax.set_yticks(range(2), ["Call", "Put"])
            ax.set_title("Jul–Aug" if split == "development" else "Sep–Dec")
            for (i, j), value in np.ndenumerate(values):
                ax.text(j, i, f"{value:+.2f}" if np.isfinite(value) else "n/a", ha="center", va="center", color="white" if abs(value) > .7 * limit else "black")
        fig.suptitle("Post-hoc: model minus midpoint, index points; equal-date means", fontsize=12)
        fig.tight_layout()
        fig.savefig(folder / "call_put_moneyness_bias.png")
        plt.close(fig)
        figures.append(("Post-hoc call/put and moneyness bias; positive means model above midpoint", "figures/call_put_moneyness_bias.png"))
    return figures

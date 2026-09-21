"""English decision report and self-contained static HTML, with no fabricated results."""

from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

import pandas as pd

from .data import sha256_file, write_json
from .validation import ValidationError, load_frozen_predictions, load_validation_result


def load_report_receipt(
    report_dir: str | Path, validation_path: str | Path, predictions: str | Path
) -> dict:
    """Verify report bytes and generating source against current validated evidence.

    This is an unsigned consistency receipt, not a publisher identity or signature.
    Consumers should also copy the diagnostic sidecar referenced by validation.
    """
    report_dir = Path(report_dir).resolve()
    validation, validation_receipt = load_validation_result(validation_path, predictions)
    receipt = json.loads((report_dir / "receipt.json").read_text(encoding="utf-8"))
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "unsigned_report_integrity_receipt"
    ):
        raise ValidationError("Unsupported report integrity receipt")
    for key in (
        "validation_sha256",
        "validator_source_sha256",
        "predictions_sha256",
        "diagnostics_sha256",
    ):
        if receipt.get(key) != validation_receipt[key]:
            raise ValidationError(f"Report uses stale validation evidence: {key}")
    if receipt.get("validation_receipt_sha256") != sha256_file(
        Path(validation_path).with_suffix(".receipt.json")
    ):
        raise ValidationError("Report uses a different validation receipt")
    expected_sources = {
        name: sha256_file(Path(__file__).parent / name)
        for name in ("reporting.py", "diagnostics.py")
    }
    if receipt.get("report_source_hashes") != expected_sources:
        raise ValidationError("Report source changed; regenerate the report")
    artifacts = receipt.get("artifact_sha256", {})
    if not {"report.md", "report.html", "data/annual.csv", "data/event_responses.csv"}.issubset(
        artifacts
    ):
        raise ValidationError("Report receipt lacks required artifacts")
    for name, expected_hash in artifacts.items():
        path = (report_dir / name).resolve()
        if not path.is_relative_to(report_dir) or not path.is_file():
            raise ValidationError(f"Report artifact missing or outside report directory: {name}")
        if sha256_file(path) != expected_hash:
            raise ValidationError(f"Report artifact changed after generation: {name}")
    if validation["diagnostics_sha256"] != receipt["diagnostics_sha256"]:
        raise ValidationError("Report diagnostic identity mismatch")
    return receipt


def _export_diagnostics(diagnostics: dict, output: Path) -> list[Path]:
    data_dir = output / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "annual": diagnostics["annual"],
        "event_responses": [
            {
                "event_id": event["event_id"],
                "anchor_date": event["anchor_date"],
                "selection": event["selection"],
                **row,
            }
            for event in diagnostics["events"]
            for row in event["models"]
        ],
        "event_series": [
            {"event_id": event["event_id"], "anchor_date": event["anchor_date"], **row}
            for event in diagnostics["events"]
            for row in event["series"]
        ],
        "currency_hpl": [
            {
                "event_id": event["event_id"],
                "anchor_date": event["anchor_date"],
                "currency": currency,
                "signed_hpl_eur": value,
            }
            for event in diagnostics["events"]
            for currency, value in event["currency_hpl_eur"].items()
        ],
    }
    artifacts = []
    for name, rows in tables.items():
        path = data_dir / f"{name}.csv"
        pd.DataFrame(rows).to_csv(path, index=False, float_format="%.17g")
        artifacts.append(path)
    return artifacts


def _diagnostic_sections(diagnostics: dict) -> list[str]:
    annual = pd.DataFrame(diagnostics["annual"])
    names = sorted(annual["model"].unique())
    rows = []
    for year, group in annual.loc[annual["split"].eq("test")].groupby("year", sort=True):
        by_name = group.set_index("model")
        rows.append(
            [
                year,
                int(group["n"].iloc[0]),
                *[
                    f"{by_name.loc[name, 'exceptions_99']:.0f} / {by_name.loc[name, 'sum_excess_99_eur'] / 1000:,.1f}"
                    for name in names
                ],
            ]
        )
    content = [
        "### Post-review calendar-year diagnostics",
        "These additions inspect the existing sample after its original results were reviewed. They do not create a fresh holdout, change model selection, or add significance tests. Every observed calendar year is retained in data/annual.csv and the annual heatmap; the compact table below shows all test years. Cells are **99% exception count / sum of positive loss-minus-VaR gaps in EUR thousands**. At nominal coverage, expected count is n × 1%; a large count in a short year is diagnostic evidence, not an independent rejection decision.",
        _table(["Year", "n", *names], rows),
    ]
    for name, group in annual.loc[annual["split"].eq("test")].groupby("model", sort=True):
        peak = group.sort_values(["exceptions_99", "year"], ascending=[False, True]).iloc[0]
        low_tail = int((group["tail_count_975"] < 20).sum())
        content.append(
            f"- {name}: its highest-count test year is {peak['year']} with {peak['exceptions_99']} / {peak['n']} exceptions "
            f"(expected {peak['expected_exceptions_99']:.2f}); positive daily VaR gaps total EUR {peak['sum_excess_99_eur']:,.0f}. "
            f"{low_tail} of {len(group)} test years have fewer than 20 ES tail observations. "
            "No annual ES inference is performed, including years that reach that count threshold."
        )
    content.extend(
        [
            "### Event response and cash attribution",
            "A ±20-observation replay separates the forecast available before the anchor from the next forecast, which can use the anchor return. The original CHF date is retained; the other anchors are **retrospectively selected worst-loss dates** within the four original stress years. They are explanatory case studies, not successful advance event predictions. Boundary windows disclose their actual pre/post counts in data/event_responses.csv. All event-day currency HPL contributions are exported in data/currency_hpl.csv; these are cash accounting contributions, not marginal VaR or causal effects.",
            _table(
                [
                    "Anchor / selection",
                    "Model",
                    "Anchor VaR EUR",
                    "Next VaR EUR",
                    "Next / anchor",
                    "Pre → post mean VaR EUR",
                    "Post hits / n",
                ],
                [
                    [
                        f"{event['anchor_date']} ({'CHF' if event['event_id'] == 'chf_floor_2015' else 'retrospective worst loss'})",
                        row["model"],
                        f"{row['anchor_var_99_eur']:,.0f}",
                        _number(row["next_var_99_eur"], 0),
                        _number(row["next_to_anchor_var_ratio"], 2),
                        f"{_number(row['pre_mean_var_99_eur'], 0)} → {_number(row['post_mean_var_99_eur'], 0)}",
                        f"{row['post_exceptions_99']} / {row['post_n']}",
                    ]
                    for event in diagnostics["events"]
                    for row in event["models"]
                ],
            ),
        ]
    )
    chf = next(
        (event for event in diagnostics["events"] if event["event_id"] == "chf_floor_2015"), None
    )
    if chf:
        content.extend(
            [
                f"**CHF accounting and timing:** signed portfolio HPL on {chf['anchor_date']} was EUR {chf['signed_hpl_eur']:+,.0f}. The table below sums to that portfolio HPL. A gain can still increase a two-sided volatility estimate and the next loss-tail forecast. That response was unavailable before the anchor and does not show that the gain needed a VaR loss buffer.",
                _table(
                    ["Currency", "Signed HPL EUR"],
                    [
                        [currency, f"{amount:+,.0f}"]
                        for currency, amount in chf["currency_hpl_eur"].items()
                    ],
                ),
            ]
        )
    content.append(
        "**Economic interpretation:** more risk buffer after an event can reduce subsequent exceptions but can also remain elevated after realised volatility falls. These plots show the timing and magnitude; they do not estimate optimal capital, trading P&L saved, or the causal benefit of a model change. The sign, observation calendar and frozen holdings remain essential to interpretation. Any proposed adaptation requires a new model version and genuinely new evaluation evidence."
    )
    return content


def _number(value, precision: int = 4) -> str:
    return "insufficient" if value is None else f"{value:.{precision}f}"


def _table(headers: list[str], rows: list[list]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(str(x) for x in row) + " |" for row in rows),
        ]
    )


def _findings(frame: pd.DataFrame, validation: dict, manifest: dict) -> list[str]:
    """Turn observed failures into limited, economically interpretable findings."""
    content = ["### Concrete findings and use restrictions"]
    test = validation["splits"].get("test", {})
    models = test.get("models", {})
    gaussian = models.get("ewma_gaussian")
    if gaussian:
        coverage = gaussian["var_99"]
        hypothesis = next(
            (row for row in test["hypotheses"] if row["name"] == "ewma_gaussian/var_99/coverage"),
            None,
        )
        decision = "rejected" if hypothesis and hypothesis["reject"] else "not rejected"
        holm = "unavailable" if hypothesis is None else _number(hypothesis["holm_p"], 6)
        content.append(
            f"**Gaussian tail coverage:** the held-out model produced "
            f"{coverage['exceptions']} exceptions in {coverage['n']:,} observations "
            f"against {coverage['expected_exceptions']:.2f} expected at 99% coverage "
            f"(Holm-adjusted p = {holm}; {decision}). This is a frequency calibration "
            "finding, not a claim that the model forecasts the timing of every loss. "
            "A Gaussian tail combined with a volatility filter can leave material "
            "tail risk underrepresented; these observations alone do not isolate the causal mechanism."
        )
        selected = validation["development_selected_model"]
        if selected in models:
            gaussian_score = gaussian["scores"]["fz0_mean"]
            selected_score = models[selected]["scores"]["fz0_mean"]
            relation = "lower (better)" if gaussian_score < selected_score else "higher (worse)"
            content.append(
                f"**Scoring and calibration answer different questions:** Gaussian held-out "
                f"FZ0 is {gaussian_score:.4f}, {relation} than the development-selected "
                f"{selected}'s {selected_score:.4f}, while its 99% coverage test is "
                f"{decision}. A good average joint score cannot replace a tail-coverage "
                "requirement, and the test-period score does not retrospectively change model selection."
            )
    hs2008 = next(
        (
            row
            for row in validation["stress"]
            if row["year"] == 2008 and row["model"] == "historical"
        ),
        None,
    )
    if hs2008:
        content.append(
            f"**Historical-window response:** during 2008, historical simulation recorded "
            f"{hs2008['exceptions_99']} 99% exceptions in {hs2008['n']} observations. "
            f"Its equally weighted {manifest['protocol']['window']}-day window retains "
            "many pre-shock observations, a plausible mechanism for slow response to a "
            "volatility regime change. Concentrated stress-period exceptions are consistent "
            "with that explanation, not causal proof; development-period independence tests "
            "and the rolling plots provide separate diagnostic evidence. Shortening the "
            "window is an unproven candidate change, not an established improvement."
        )
    stress2022 = next((row for row in validation["stress"] if row["year"] == 2022), None)
    if stress2022:
        day = stress2022["worst_date"]
        observed = frame.loc[frame["date"] == day].sort_values("model")
        content.extend(
            [
                (
                    f"**Economic magnitude on {day}:** this was the largest observed loss within "
                    "the predeclared 2022 calendar-year window. The day was identified retrospectively "
                    "for explanation, not used to tune a model. A positive gap below is the amount "
                    "by which realised loss exceeded that day's 99% VaR; it is not a claim about "
                    "avoidable trading loss or required regulatory capital."
                ),
                _table(
                    ["Model", "Realised loss EUR", "99% VaR EUR", "Loss above VaR EUR"],
                    [
                        [
                            row.model,
                            f"{row.loss_eur:,.0f}",
                            f"{row.var_99_eur:,.0f}",
                            f"{max(row.loss_eur - row.var_99_eur, 0):,.0f}",
                        ]
                        for row in observed.itertuples()
                    ],
                ),
            ]
        )
    if gaussian and any(
        row["name"] == "ewma_gaussian/var_99/coverage" and row["reject"]
        for row in test["hypotheses"]
    ):
        content.append(
            "**Use restriction:** this study does not support Gaussian VaR as stand-alone "
            "tail-risk approval evidence. Any restricted use needs independent stress and "
            "ES monitoring, with explicit attention to regime changes and forecast gaps. "
            "FHS and HS non-rejection also does not grant approval. A proposed tail model "
            "or window change must be a new version with new evidence; no improvement "
            "benefit has been demonstrated by the current experiment."
        )
    return content


def _figures(frame: pd.DataFrame, validation: dict, output: Path) -> list[tuple[str, str]]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    selected = validation["development_selected_model"] or min(frame["model"].unique())
    chosen = frame.loc[(frame["model"] == selected) & frame["split"].eq("test")]
    if chosen.empty:
        chosen = frame.loc[frame["model"] == selected]
    times = pd.to_datetime(chosen["date"])
    assets = output / "figures"
    assets.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 4), constrained_layout=True)
    ax.plot(
        times,
        chosen["loss_eur"] / 1000,
        color="#758896",
        alpha=0.55,
        linewidth=0.6,
        label="Realised HPL loss",
    )
    ax.plot(
        times, chosen["var_99_eur"] / 1000, color="#bc592c", linewidth=0.8, label="One-day 99% VaR"
    )
    hits = chosen["loss_eur"] > chosen["var_99_eur"]
    ax.scatter(
        times[hits],
        chosen.loc[hits, "loss_eur"] / 1000,
        color="#aa2233",
        s=11,
        label="Exceptions",
        zorder=3,
    )
    ax.set(
        title=f"Development-selected model: {selected} | frozen cash book",
        ylabel="EUR thousands; loss positive",
    )
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    fig.savefig(assets / "loss_and_var.png", dpi=150)
    plt.close(fig)

    split = "test" if "test" in validation["splits"] else "development"
    models = validation["splits"][split]["models"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    names = list(models)
    labels = [name.replace("_", "\n") for name in names]
    axes[0].bar(labels, [models[n]["scores"]["fz0_mean"] for n in names], color="#28556a")
    axes[0].set(title=f"{split.title()} joint VaR–ES score", ylabel="Mean FZ0 (lower is better)")
    axes[1].bar(labels, [models[n]["var_99"]["exceptions"] for n in names], color="#bf7d50")
    axes[1].axhline(
        next(iter(models.values()))["n"] * 0.01,
        color="#303e47",
        linestyle="--",
        label="Expected count at 99%",
    )
    axes[1].set(title="Coverage alone cannot rank models", ylabel="99% VaR exceptions")
    axes[1].legend(fontsize=8)
    fig.savefig(assets / "model_comparison.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 3.5), constrained_layout=True)
    for name, group in frame.loc[frame["split"] == split].groupby("model"):
        hit = (group["loss_eur"] > group["var_99_eur"]).astype(float)
        ax.plot(
            pd.to_datetime(group["date"]),
            hit.rolling(250, min_periods=250).sum(),
            label=name,
            linewidth=0.8,
        )
    ax.axhline(2.5, color="#303e47", linestyle="--", linewidth=0.8)
    ax.set(
        title="Rolling 250-observation exception counts: diagnostic, not repeated approval tests",
        ylabel="99% VaR exceptions",
    )
    ax.legend(fontsize=8, ncol=3)
    fig.savefig(assets / "rolling_exceptions.png", dpi=150)
    plt.close(fig)
    return [
        ("loss_and_var.png", "Frozen forecast versus realised hypothetical cash-book loss."),
        (
            "model_comparison.png",
            "Proper joint scoring prevents an unlimited risk buffer from winning on exception counts alone.",
        ),
        (
            "rolling_exceptions.png",
            "Rolling windows overlap and have low tail counts; interpret descriptively.",
        ),
    ]


def _diagnostic_figures(diagnostics: dict, output: Path) -> list[tuple[str, str]]:
    import matplotlib.pyplot as plt
    import numpy as np

    annual = pd.DataFrame(diagnostics["annual"])
    counts = annual.pivot(index="model", columns="year", values="exceptions_99").sort_index()
    gaps = (
        annual.pivot(index="model", columns="year", values="sum_excess_99_eur").reindex(
            counts.index
        )
        / 1000
    )
    fig, axes = plt.subplots(2, 1, figsize=(12, 5.5), constrained_layout=True)
    for ax, values, title, unit in (
        (axes[0], counts, "99% exceptions by calendar year", "Count"),
        (axes[1], gaps, "Sum of positive daily loss-minus-VaR gaps", "EUR thousands"),
    ):
        heatmap = ax.imshow(values.to_numpy(), aspect="auto", cmap="YlOrRd", vmin=0)
        ax.set(
            yticks=np.arange(len(values.index)),
            yticklabels=values.index,
            xticks=np.arange(len(values.columns)),
            xticklabels=values.columns,
            title=title,
        )
        ax.tick_params(axis="x", labelrotation=45, labelsize=8)
        for r in range(len(values.index)):
            for c in range(len(values.columns)):
                value = values.iloc[r, c]
                if pd.notna(value):
                    ax.text(
                        c,
                        r,
                        f"{value:.0f}",
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white" if value > values.max().max() * 0.6 else "#24383e",
                    )
        split_year = annual.loc[annual["split"].eq("test"), "year"].min()
        if pd.notna(split_year) and split_year in values.columns:
            ax.axvline(list(values.columns).index(split_year) - 0.5, color="#19445b", linewidth=2)
        fig.colorbar(heatmap, ax=ax, label=unit, shrink=0.85, pad=0.02)
    fig.suptitle(
        "All observed years retained | divider marks test start | descriptive, no annual tests",
        fontsize=11,
    )
    fig.savefig(output / "figures" / "annual_diagnostics.png", dpi=150)
    plt.close(fig)

    events = diagnostics["events"]
    fig, axes = plt.subplots(
        max(len(events), 1),
        1,
        figsize=(12, 2.5 * max(len(events), 1)),
        constrained_layout=True,
        squeeze=False,
    )
    colors = {"historical": "#ba622b", "ewma_gaussian": "#327699", "ewma_fhs": "#528958"}
    if not events:
        axes[0, 0].text(
            0.5, 0.5, "No original stress-event dates in this fixture", ha="center", va="center"
        )
    for ax, event in zip(axes[:, 0], events, strict=False):
        values = pd.DataFrame(event["series"])
        realized = values.drop_duplicates("date").sort_values("relative_observation")
        ax.bar(
            realized["relative_observation"],
            realized["loss_eur"] / 1000,
            color="#a5b4bc",
            width=0.7,
            label="Realised loss (gain < 0)",
        )
        for name, group in values.groupby("model", sort=True):
            ax.plot(
                group["relative_observation"],
                group["var_99_eur"] / 1000,
                color=colors.get(name),
                label=name,
                linewidth=1.1,
            )
        ax.axvline(0, color="#333333", linestyle="--", linewidth=0.8)
        label = (
            "original CHF anchor"
            if event["event_id"] == "chf_floor_2015"
            else "retrospective stress-year worst loss"
        )
        ax.set(
            title=f"{event['anchor_date']} | {label}", ylabel="EUR thousands", xlim=(-20.7, 20.7)
        )
        ax.axhline(0, color="#555555", linewidth=0.4)
    axes[0, 0].legend(fontsize=8, ncol=4, loc="upper left")
    axes[-1, 0].set_xlabel(
        "Observed trading dates relative to anchor; day 0 forecast uses day -1 information"
    )
    fig.savefig(output / "figures" / "event_responses.png", dpi=150)
    plt.close(fig)
    return [
        (
            "annual_diagnostics.png",
            "Exhaustive yearly evidence separates exception frequency from gap magnitude; incomplete years keep their actual n in the CSV.",
        ),
        (
            "event_responses.png",
            "Event replay preserves signed HPL and information timing. A day +1 risk response cannot cover day 0 retroactively.",
        ),
    ]


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _render_html(markdown: str, output: Path) -> str:
    blocks = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [x.strip() for x in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", x) for x in cells):
                    tag = "th" if not rows else "td"
                    rows.append(
                        "<tr>" + "".join(f"<{tag}>{_inline(x)}</{tag}>" for x in cells) + "</tr>"
                    )
                i += 1
            blocks.append("<div class='table-wrap'><table>" + "".join(rows) + "</table></div>")
            continue
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        heading = re.match(r"^(#{1,4}) (.+)$", line)
        if image:
            encoded = base64.b64encode((output / image.group(2)).read_bytes()).decode()
            blocks.append(
                f"<figure><img alt='{html.escape(image.group(1))}' src='data:image/png;base64,{encoded}'><figcaption>{_inline(image.group(1))}</figcaption></figure>"
            )
        elif heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif line.startswith("- "):
            blocks.append(f"<p class='bullet'>• {_inline(line[2:])}</p>")
        elif line.strip():
            blocks.append("<p>" + _inline(line) + "</p>")
        i += 1
    style = """body{margin:0;background:#eef2f3;color:#20343e;font:16px/1.6 system-ui,sans-serif}main{max-width:1160px;margin:32px auto;padding:44px;background:white;border-top:7px solid #28556a;box-shadow:0 4px 22px #132b3510}h1{font-size:34px;line-height:1.2}h2{margin-top:36px;border-top:1px solid #d9e1e5;padding-top:20px}h3{margin-top:25px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px 11px;text-align:left;border-bottom:1px solid #dbe3e6;vertical-align:top}th{background:#e7eef1}.table-wrap{overflow:auto;margin:20px 0}img{width:100%;height:auto}figure{margin:25px 0}figcaption{font-size:13px;color:#536d78}code{font-size:13px;overflow-wrap:anywhere;background:#edf2f5;padding:1px 3px}.bullet{margin:5px 0}p{overflow-wrap:anywhere}@media(max-width:700px){main{padding:20px;margin:0}h1{font-size:27px}}@media print{main{box-shadow:none;margin:0;padding:10px}h2{break-after:avoid}tr,figure{break-inside:avoid}}"""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Independent FX Market Risk Validation</title><style>{style}</style></head><body><main>{''.join(blocks)}</main></body></html>"


def report(predictions: str | Path, validation_path: str | Path, output_dir: str | Path) -> dict:
    frame, manifest = load_frozen_predictions(predictions)
    validation, receipt = load_validation_result(validation_path, predictions)
    if validation.get("predictions_sha256") != sha256_file(predictions):
        raise ValueError("Validation was not produced from these frozen predictions")
    if validation.get("protocol_sha256") != manifest["protocol_sha256"]:
        raise ValueError("Validation protocol identity mismatch")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    diagnostics = json.loads(
        Path(validation_path).with_suffix(".diagnostics.json").read_text(encoding="utf-8")
    )
    diagnostic_files = _export_diagnostics(diagnostics, output)
    figures = _figures(frame, validation, output)
    figures.extend(_diagnostic_figures(diagnostics, output))
    selected = validation["development_selected_model"]
    test_models = validation["splits"].get("test", {}).get("models", {})
    assessment = test_models.get(selected, {}).get("assessment", "no held-out result available")
    p = manifest["protocol"]
    sections = [
        "# Independent FX Market Risk Validation",
        "## 1. Executive decision",
        f"The development-selected model is **{selected}**. Its held-out statistical assessment is **{assessment}**. Selection uses development FZ0 only; the held-out sample does not choose the model.",
        "This is a research validation decision, not a production approval. A non-rejected hypothesis does not establish correctness. Model rejection is a valid project outcome and must remain in the evidence.",
        *_findings(frame, validation, manifest),
        "## 2. Data, portfolio and information set",
        f"Source period: **{manifest['source_first_date']} to {manifest['source_last_date']}**, {manifest['source_rows_used']:,} observed ECB dates. Data source: ECB reference rates. Derived returns and risk measures are this project's calculations.",
        f"Inception: **{manifest['holdings']['inception_date']}**; first realised HPL forecast: **{manifest['holdings']['first_forecast_date']}**. The book starts with EUR {p['eur_per_currency_at_inception']:,.0f} equivalent in each of USD, GBP, JPY, CHF and AUD; foreign units then remain fixed. There is no rebalancing or interest carry.",
        "ECB quotes are foreign currency per EUR. EUR cash prices are their inverses. Exact next-day HPL is the fixed foreign quantity multiplied by the change in EUR cash price. All risk models use simple EUR cash-asset returns. The previous observed date is the forecast information date; no holiday filling or tail-event clipping occurs.",
        _table(
            ["Currency", "Frozen foreign units"],
            [[c, f"{v:,.4f}"] for c, v in manifest["holdings"]["foreign_units"].items()],
        ),
        "## 3. Frozen model protocol",
        _table(
            ["Model", "Specification"],
            [
                [
                    "historical",
                    f"Last {p['window']} joint asset-return vectors, equal scenario weights, exact cash repricing.",
                ],
                [
                    "ewma_gaussian",
                    f"Zero mean, EWMA covariance with lambda {p['ewma_decay']}; analytical Gaussian VaR and ES.",
                ],
                [
                    "ewma_fhs",
                    f"Last {p['window']} joint vectors divided by their own prior-day EWMA volatilities, then rescaled to current prior-day volatility; no independent per-currency resampling.",
                ],
            ],
        ),
        f"EWMA initializes from {p['ewma_initial_window']} prior returns. Inverse empirical-CDF VaR and probability-integrated upper-tail ES are used. Outputs are 97.5% VaR/ES and 99% VaR. Development ends {p['development_end']}; held-out test begins {p['test_start']} and ends {p['end']}.",
        "## 4. Independent statistical validation",
        "The validator reads frozen forecast rows, independently rebuilds inception allocations and daily cash HPL from source FX and frozen native quantities, and checks every model's information window. It verifies input, protocol and model-source hashes without calling the forecasting engines. A separate receipt binds the validation results, run manifest, predictions and validator source before reporting; this is an unsigned consistency check, not a digital signature. Exact two-sided binomial coverage tests and Clopper-Pearson intervals accompany Kupiec likelihood ratios. Christoffersen independence ratios use a conditional permutation reference distribution; asymptotic p-values are also retained for comparison.",
        f"ES uses the Acerbi–Szekely Z2 moment in loss convention, centered circular moving-block bootstrap with block length {validation['block_length']} and {validation['bootstrap_samples']:,} draws. A positive moment indicates tail loss above forecast. This is an approximate weak-dependence/local-stability inference procedure, affected by VaR misspecification. Fewer than 20 realised tail events gives **insufficient evidence**.",
        "Primary available coverage, independence and ES-underestimation hypotheses receive Holm correction separately within each split. Repeated 250-day windows and stress-year views are descriptive. They are not independent repeated approval tests.",
        "FZ0 jointly scores 97.5% VaR and ES; pinball loss scores each VaR. Losses are normalized by inception gross notional, EUR 5m under the standard protocol. Lower scores are better; arbitrarily inflating VaR/ES does not earn a win merely by suppressing exceptions.",
        "## 5. Observed results",
    ]
    for split, content in validation["splits"].items():
        sections.append(f"### {split.title()}")
        sections.append(
            _table(
                ["Model", "n", "99% exceptions", "Expected", "FZ0", "ES moment", "Assessment"],
                [
                    [
                        name,
                        r["n"],
                        r["var_99"]["exceptions"],
                        _number(r["var_99"]["expected_exceptions"], 1),
                        _number(r["scores"]["fz0_mean"]),
                        _number(r["es_975"]["moment"]),
                        r["assessment"],
                    ]
                    for name, r in content["models"].items()
                ],
            )
        )
        sections.append(
            _table(
                ["Hypothesis", "Raw p", "Holm p", "Reject at 5%"],
                [
                    [
                        x["name"],
                        _number(x["raw_p"]),
                        _number(x["holm_p"]),
                        "yes" if x["reject"] else "no",
                    ]
                    for x in content["hypotheses"]
                ],
            )
        )
        for name, r in content["models"].items():
            ci = r["es_975"]["moment_ci_95"]
            ci_text = "unavailable" if ci is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"
            sections.append(
                f"- {name}: ES tail events {r['es_975']['tail_count']}; ES evidence {r['es_975']['status']}; approximate 95% moment interval {ci_text}. Mean 99% VaR EUR {r['scores']['mean_var_99_eur']:,.0f}; mean 97.5% ES EUR {r['scores']['mean_es_975_eur']:,.0f}."
            )
    sections.append("## 6. Visual diagnostics")
    sections.extend(f"![{caption}](figures/{name})" for name, caption in figures)
    sections.extend(
        [
            "## 7. Predeclared stress years",
            "Full calendar years 2008, 2015, 2020 and 2022 are shown without significance claims. 2008 belongs to development; later stress years belong to the held-out sample. Worst days below are descriptive observations, not new tuning targets.",
            _table(
                [
                    "Year",
                    "Model",
                    "99% hits / n",
                    "Worst date",
                    "Worst loss EUR",
                    "VaR on that day EUR",
                ],
                [
                    [
                        x["year"],
                        x["model"],
                        f"{x['exceptions_99']} / {x['n']}",
                        x["worst_date"],
                        f"{x['worst_loss_eur']:,.0f}",
                        f"{x['var_99_on_worst_day_eur']:,.0f}",
                    ]
                    for x in validation["stress"]
                ],
            ),
            "### Signed CHF event replay",
            "The predeclared 14–16 January 2015 window is distinct from the worst loss in all of 2015. Positive HPL is a gain. In particular, a long CHF cash exposure can gain on the floor-removal day; no gain is relabeled as a loss.",
            _table(
                ["Date", "Model", "Signed HPL EUR", "99% VaR EUR", "Loss exception"],
                [
                    [
                        x["date"],
                        x["model"],
                        f"{x['signed_hpl_eur']:,.0f}",
                        f"{x['var_99_eur']:,.0f}",
                        "yes" if x["exception_99"] else "no",
                    ]
                    for x in validation.get("events", [])
                ],
            ),
            *_diagnostic_sections(diagnostics),
            "## 8. Limitations and follow-up",
            *("- " + text for text in validation["limitations"]),
            "- Fixed long cash exposures do not establish performance for options, leveraged trading, dynamic hedging or funding-sensitive portfolios. Gaussian support and FHS volatility scaling are modeling assumptions.",
            "- Reference rates are not executable prices. There are no transaction-cost, liquidity-horizon, FRTB capital or production-control claims.",
            "- A rejection requires investigating the pattern and economic cause. A changed specification requires a new version and fresh holdout; the current test period cannot be recycled as independent evidence.",
            "## 9. Provenance and reproduction",
            f"Data SHA-256: `{manifest['source_sha256']}`",
            f"Protocol SHA-256: `{manifest['protocol_sha256']}`",
            f"Model-source SHA-256: `{manifest['model_source_sha256']}`",
            f"Predictions SHA-256: `{manifest['predictions_sha256']}`",
            f"Validation SHA-256: `{receipt['validation_sha256']}`",
            f"Validator-source SHA-256: `{receipt['validator_source_sha256']}`",
            f"Frozen run time UTC: `{manifest['frozen_at_utc']}`. Validation seed: `{validation['seed']}`. See run_manifest.json, protocol.json, holdings.json, predictions.csv and validation.json for machine-readable evidence.",
            "## 10. Management summary and interview notes / 管理摘要与面试说明",
            f"开发期按联合评分选出 {selected}；封存测试给出的结论为 {assessment}。这不是上线批准，也不是模型正确性的证明。应结合尾部损失、超越聚集、统计不确定性和风险预测成本判断用途。",
            "面试重点：先说明现金头寸与价格口径，再解释为何不能随机拆分时间序列、为何历史波动率必须只使用当时已有信息，以及为何通过VaR覆盖检验仍可能低估ES。",
            "项目的价值在于可复核的判断链：官方真实数据 → 冻结协议和预测 → 独立验证 → 反例与限制。模型被拒绝应如实报告；把VaR放大到没有超越并不是改进。",
            "## 11. Method sources",
            "ECB reference rates: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
            "Acerbi and Szekely (2014), Backtesting Expected Shortfall: https://www.msci.com/resources/research/articles/2014/Research_Insight_Backtesting_Expected_Shortfall_December_2014.pdf",
            "Patton, Ziegel and Chen (2019), equation 6, FZ0: https://public.econ.duke.edu/~ap172/Patton_Ziegel_Chen_JoE_2019.pdf",
        ]
    )
    markdown = "\n\n".join(sections) + "\n"
    (output / "report.md").write_text(markdown, encoding="utf-8")
    (output / "report.html").write_text(_render_html(markdown, output), encoding="utf-8")
    artifacts = [output / "report.md", output / "report.html", *diagnostic_files]
    artifacts.extend(output / "figures" / name for name, _ in figures)
    write_json(
        output / "receipt.json",
        {
            "schema_version": 1,
            "kind": "unsigned_report_integrity_receipt",
            **{
                key: receipt[key]
                for key in (
                    "validation_sha256",
                    "validator_source_sha256",
                    "predictions_sha256",
                    "diagnostics_sha256",
                )
            },
            "validation_receipt_sha256": sha256_file(
                Path(validation_path).with_suffix(".receipt.json")
            ),
            "report_source_hashes": {
                name: sha256_file(Path(__file__).parent / name)
                for name in ("reporting.py", "diagnostics.py")
            },
            "artifact_sha256": {
                path.relative_to(output).as_posix(): sha256_file(path) for path in artifacts
            },
            "assurance": "Unsigned artifact/source consistency; not a digital signature or fresh holdout.",
        },
    )
    return {
        "markdown": str((output / "report.md").resolve()),
        "html": str((output / "report.html").resolve()),
    }

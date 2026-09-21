"""Synthetic falsification/size audit of the independent validation routines.

These are controlled simulations, never presented as observed market results.
Formal and fast protocols are fixed presets, with their seeds and repetitions saved.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.stats import beta, norm, t

from .data import sha256_file, write_json
from .validation import (
    ValidationError,
    es_backtest,
    fz0_scores,
    validator_source_identity,
    var_backtest,
)


def load_audit_receipt(output_dir: str | Path) -> dict:
    """Reject stale/tampered audit artifacts before publishing synthetic evidence."""
    destination = Path(output_dir)
    receipt = json.loads((destination / "audit.receipt.json").read_text(encoding="utf-8"))
    expected_sources = {**validator_source_identity(), "audit.py": sha256_file(__file__)}
    if receipt.get("schema_version") != 1 or receipt.get("source_hashes") != expected_sources:
        raise ValidationError("Audit source changed; re-run the synthetic audit")
    if set(receipt.get("artifact_sha256", {})) != {"audit.json", "audit.md"}:
        raise ValidationError("Audit receipt lacks required artifacts")
    for name, expected in receipt["artifact_sha256"].items():
        if sha256_file(destination / name) != expected:
            raise ValidationError(f"Audit artifact changed after generation: {name}")
    result = json.loads((destination / "audit.json").read_text(encoding="utf-8"))
    if (
        result.get("validation_source_sha256") != expected_sources["validation.py"]
        or result.get("audit_source_sha256") != expected_sources["audit.py"]
    ):
        raise ValidationError("Audit result does not bind current source")
    if result.get("preset") != receipt.get("preset") or result.get("protocol") != PRESETS.get(
        result.get("preset")
    ):
        raise ValidationError("Audit protocol differs from its recorded preset")
    return receipt


PRESETS = {
    "fast": {
        "repetitions": 12,
        "observations": 2000,
        "bootstrap_samples": 199,
        "permutations": 199,
        "block_length": 20,
        "seed": 20260920,
    },
    "formal": {
        "repetitions": 200,
        "observations": 5000,
        "bootstrap_samples": 999,
        "permutations": 999,
        "block_length": 20,
        "seed": 20260920,
    },
}


def _proportion_interval(successes: int, count: int) -> list[float]:
    return [
        0.0 if not successes else float(beta.ppf(0.025, successes, count - successes + 1)),
        1.0 if successes == count else float(beta.ppf(0.975, successes + 1, count - successes)),
    ]


def audit(output_dir: str | Path, preset: str = "fast") -> dict:
    if preset not in PRESETS:
        raise ValueError("Audit preset must be fast or formal")
    config = PRESETS[preset]
    rng = np.random.default_rng(config["seed"])
    n, repetitions = config["observations"], config["repetitions"]
    alpha, q, df = 0.975, 0.025, 5
    normal_var = float(norm.ppf(alpha))
    normal_es = float(norm.pdf(normal_var) / q)
    t_scale = np.sqrt((df - 2) / df)
    t_quantile = float(t.ppf(alpha, df))
    t_var = t_quantile * t_scale
    t_es = t_scale * (df + t_quantile**2) / (df - 1) * float(t.pdf(t_quantile, df)) / q
    names = (
        "normal_correct",
        "student_t5_correct",
        "student_t5_as_gaussian",
        "clustered_hits",
        "es_only_20pct_low",
        "risk_buffer_5x",
    )
    collected = {
        name: {
            "coverage_rejections": 0,
            "independence_rejections": 0,
            "es_underestimation_rejections": 0,
            "es_available": 0,
            "fz0_difference_from_correct": [],
        }
        for name in names
    }
    for repetition in range(repetitions):
        normal_loss = rng.standard_normal(n)
        heavy_loss = rng.standard_t(df, size=n) * t_scale
        # Marginally N(0,1): mix truncated normal body/tail using a stationary
        # Markov hit process with tail probability q and P(hit|hit)=0.5.
        hits = np.empty(n, dtype=bool)
        hits[0] = rng.random() < q
        p11 = 0.5
        p01 = q * (1 - p11) / (1 - q)
        for i in range(1, n):
            hits[i] = rng.random() < (p11 if hits[i - 1] else p01)
        uniforms = rng.random(n)
        uniforms = np.where(hits, alpha + q * uniforms, alpha * uniforms)
        clustered = norm.ppf(uniforms)
        scenarios = {
            "normal_correct": (normal_loss, normal_var, normal_es, normal_var, normal_es),
            "student_t5_correct": (heavy_loss, t_var, t_es, t_var, t_es),
            "student_t5_as_gaussian": (heavy_loss, normal_var, normal_es, t_var, t_es),
            "clustered_hits": (clustered, normal_var, normal_es, normal_var, normal_es),
            "es_only_20pct_low": (heavy_loss, t_var, 0.8 * t_es, t_var, t_es),
            "risk_buffer_5x": (normal_loss, 5 * normal_var, 5 * normal_es, normal_var, normal_es),
        }
        for scenario_index, (name, (loss, v, e, correct_v, correct_e)) in enumerate(
            scenarios.items()
        ):
            var, es = np.full(n, v), np.full(n, e)
            seed = config["seed"] + repetition * 100 + scenario_index
            coverage = var_backtest(loss, var, alpha, simulations=config["permutations"], seed=seed)
            tail = es_backtest(
                loss,
                var,
                es,
                samples=config["bootstrap_samples"],
                block_length=config["block_length"],
                seed=seed + 50,
            )
            item = collected[name]
            item["coverage_rejections"] += int(coverage["coverage_exact_p"] < 0.05)
            item["independence_rejections"] += int(
                coverage["independence_permutation_p"] is not None
                and coverage["independence_permutation_p"] < 0.05
            )
            if tail["underestimation_p"] is not None:
                item["es_available"] += 1
                item["es_underestimation_rejections"] += int(tail["underestimation_p"] < 0.05)
            correct_score = fz0_scores(loss, np.full(n, correct_v), np.full(n, correct_e))
            item["fz0_difference_from_correct"].append(
                float(np.mean(fz0_scores(loss, var, es) - correct_score))
            )
    results = {}
    for name, item in collected.items():
        result = {"repetitions": repetitions, "es_available": item["es_available"]}
        for key in (
            "coverage_rejections",
            "independence_rejections",
            "es_underestimation_rejections",
        ):
            denominator = (
                item["es_available"] if key == "es_underestimation_rejections" else repetitions
            )
            result[key] = item[key]
            result[key + "_rate"] = item[key] / denominator if denominator else None
            result[key + "_rate_ci_95"] = (
                _proportion_interval(item[key], denominator) if denominator else None
            )
        result["fz0_mean_difference_from_correct"] = float(
            np.mean(item["fz0_difference_from_correct"])
        )
        results[name] = result
    output = {
        "kind": "synthetic_validation_audit_not_market_evidence",
        "preset": preset,
        "protocol": config,
        "alpha": alpha,
        "significance_level": 0.05,
        "results": results,
        "validation_source_sha256": sha256_file(Path(__file__).with_name("validation.py")),
        "audit_source_sha256": sha256_file(__file__),
        "interpretation": [
            "Each test is assessed at nominal 5% before Holm; these repetitions estimate size/power, not individual model approvals.",
            "Correct-distribution rejection frequencies have binomial uncertainty; do not require every null sample to pass.",
            "The clustered scenario preserves normal marginal tails while violating temporal independence.",
            "ES-only distortion retains the correct Student-t VaR and lowers ES while preserving ES >= VaR.",
            "The 5x buffer is judged on coverage and FZ0, not rewarded for suppressing exceptions.",
            "Fast preset is a smoke audit with wide intervals; formal preset is the predeclared statistical experiment.",
            "Bootstrap inference remains approximate; any material size distortion is a limitation to report, not tune away on market holdout.",
        ],
    }
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "audit.json", output)
    lines = [
        "# Synthetic audit of the validation methods",
        "",
        f"Preset: **{preset}**. These are synthetic controls, not market performance.",
        "",
        f"Protocol: {config}",
        "",
        "| Scenario | Coverage rejection rate | Independence rejection rate | ES-underestimation rejection rate | Mean FZ0 difference vs correct forecast |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, result in results.items():
        values = [
            result[key + "_rate"]
            for key in (
                "coverage_rejections",
                "independence_rejections",
                "es_underestimation_rejections",
            )
        ]
        rendered = ["insufficient" if value is None else f"{value:.3f}" for value in values]
        lines.append(
            f"| {name} | {' | '.join(rendered)} | {result['fz0_mean_difference_from_correct']:.4f} |"
        )
    lines.extend(
        [
            "",
            *["- " + text for text in output["interpretation"]],
            "",
            "The JSON includes exact binomial 95% intervals and denominators for every rejection frequency.",
        ]
    )
    (destination / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(
        destination / "audit.receipt.json",
        {
            "schema_version": 1,
            "kind": "unsigned_synthetic_audit_integrity_receipt",
            "preset": preset,
            "source_hashes": {**validator_source_identity(), "audit.py": sha256_file(__file__)},
            "artifact_sha256": {
                name: sha256_file(destination / name) for name in ("audit.json", "audit.md")
            },
            "assurance": "Artifact/source consistency only; not a digital signature or market evidence.",
        },
    )
    return output

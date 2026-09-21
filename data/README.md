# Research data

Run `python scripts/fetch_data.py --dataset all --data-dir data` from the repository root.
The command retrieves freely accessible research inputs without accounts or payments.
It keeps original responses in `raw/`, checks cached hashes, supports conditional
HTTP resume, and writes provenance and cleaning decisions in `manifests/`.
Use `--dataset fx`, `--dataset rates`, or `--dataset options` to fetch one source.
Completed caches must match their recorded source URL, byte count, and SHA-256;
they are not silently refreshed. An interrupted HTTP transfer resumes only when
the server supplies a matching ETag or Last-Modified validator. A successful
cached run rechecks and rebuilds processed outputs without a new download.

`raw/` and `processed/` are ignored by Git. In particular, never redistribute the
HistoricalData.net sample archive or extracted contract-level CSVs. Review its
[terms](https://historicaldata.net/terms.html) and credit the provider in published
research. Free sample evaluation is expressly allowed; free access is not an open
data license. The downloader never runs code supplied inside the archive.

Outputs:

- `processed/fx.csv`: dates and USD, GBP, JPY, CHF, AUD; foreign currency units per EUR.
- `processed/rates.csv`: Federal Reserve DGS3MO observations expressed as annual decimals.
- `processed/options/`: 127 original daily CSVs from the provider's 2022H2 sample.

The FX source is the [ECB historical reference-rate ZIP](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip).
Its original wide CSV is preserved. `raw/ecb_fx_1999_2025_long.csv` is a clearly
identified normalization of that CSV, not an original SDMX response. The source
history may extend beyond the experiment; only 1999-01-01 through 2025-12-31 enters
the processed file. The first observation is 1999-01-04. All five currencies have
6,913 common observations; no missing values or non-trading dates are filled.

Rates come from [FRED DGS3MO](https://fred.stlouisfed.org/series/DGS3MO), whose
originator is the Federal Reserve Board's H.15 release. The June–December 2022
download has 146 observed dates after omitting missing holiday cells. Dividing
percent quotes by 100 produces `rate`; discount-curve construction and strictly
prior-date selection remain explicit study assumptions.

The [HistoricalData.net free sample](https://historicaldata.net/samples.html)
contains 4,294,301 rows across 127 days (2022-07-01 through 2022-12-30). Extraction
checks the publisher's complete file list, SHA-256, byte counts and row counts,
plus the 34-column schema, dates, numeric types, unique contract keys and encoded
contract expiry/type/strike. Provider documentation and license stay in `raw/`;
its Python verifier is neither extracted nor executed. The validator implements
the relevant integrity and study-input checks independently, without claiming
to reproduce every provider solver invariant.

ECB reference rates are indicative, not tradeable quotes. DGS3MO is a Treasury
investment-basis yield, not a zero curve. The option archive lacks quote timestamps
for 2022 and its end-of-day standing quotes are not synchronized. A provider's
checksum confirms delivery integrity, not correctness of the underlying quotes.
All 2022 option quote timestamps are absent; missing timestamps are never
fabricated from quote dates. Five dates contain differing SPX and SPXW underlying
closes, with a maximum difference of 3.05 index points. Detailed aggregate counts
and dates are recorded in `manifests/options.json`. Provider IV and Greek fields
are computed outputs and must not serve as independent pricing truth.

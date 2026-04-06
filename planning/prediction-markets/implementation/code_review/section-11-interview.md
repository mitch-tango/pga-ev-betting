# Section 11 Code Review Interview

## User Decision

**Q: Conftest fixtures are unused by this test file. Wire them in, keep as shared infra, or remove?**
A: Keep as-is (Recommended). Fixtures stay in conftest for other test files to adopt later.

## Auto-fixes Applied

1. **Strengthened assertions**: Changed `isinstance(results, list)` to also check `len(results) > 0` in key tests (`test_edge_calculation_with_all_markets`, `test_dg_only_pipeline`). Added favorable DG odds to first player so edges are actually generated.

2. **Removed overly permissive fallbacks**: Changed `"Polymarket unavailable" in source or "Polymarket" in source` to just `"Polymarket unavailable" in source` (same for ProphetX).

3. **Fixed file handle leaks**: Replaced all `open(mod.__file__).read()` with `Path(mod.__file__).read_text()`.

## Let Go

- Dead-heat correctness: already thoroughly tested in `test_edge_prediction_markets.py::TestDeadHeatBypass`
- Config patch targets: `@patch("config.POLYMARKET_ENABLED")` works correctly because `_pull_*_block` reads `config.POLYMARKET_ENABLED` at call time
- `test_best_book_can_be_any_prediction_market` as dataclass test: sufficient since end-to-end best_book selection is tested in `test_edge_prediction_markets.py`

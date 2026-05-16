# Test fixtures

Drop broker screenshots here when you need to add a regression test that exercises the real extractor.

Real images are gitignored — keep only this README in version control. When you add a fixture-backed test, document the expected holdings in the test file (not in this folder) so the test is self-describing.

For Korean brokerage regressions, record these facts in the test:

- broker/app name if visible
- whether ticker symbols are visible
- whether share count is visible
- which currency token appears (`원`, `₩`, `KRW`, `$`, `USD`)
- whether gain/loss amount and percent are shown on the same row

Checked-in tests should prefer mocked extractor responses. Local fixture-backed smoke tests are optional and should skip cleanly when the image file is absent.

# Final submission checklist

## Repository
- [x] Version and changelog included.
- [x] Final project summary included.
- [x] Author and citation metadata included.
- [x] All-rights-reserved license included.
- [x] Source, templates, static assets, tests and deployment files present.
- [x] Database, face photos, exports and environment secrets ignored.

## Automated validation
- [x] Python compilation passes in GitHub Actions.
- [x] Authentication and teacher-isolation tests pass.
- [x] Database and report tests pass.
- [x] Recognition edge-case and quality tests pass.
- [x] Multi-photo and HEIC tests pass.
- [x] Template-rendering and calibration tests pass.
- [x] Security middleware tests pass.
- [x] Dependency vulnerability audit passes.
- [x] Dockerfile validation passes.

## Before the live demonstration
- [ ] Pull the latest `main` branch.
- [ ] Run `run.bat` or `run.sh` once before presentation day.
- [ ] Use consented demo photographs, not public student biometric data.
- [ ] Create a small demo class and verify the camera/photo workflow.
- [ ] Confirm Excel opens correctly on the presentation laptop.
- [ ] Keep a manual-attendance fallback and a copy of the slides/report.

## Claims to avoid
- Do not claim 100% accuracy.
- Do not call the confidence score a calibrated probability.
- Do not claim liveness or anti-spoofing.
- Do not claim automatic legal compliance.
- Do not deploy a public biometric database for the demonstration.

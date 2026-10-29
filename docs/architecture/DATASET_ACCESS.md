# PHME 2022 access decision — 2026-10-27 KST

**Decision: NO-GO for PHME raw data in S0; use explicitly labeled synthetic PCB data in S1.** No raw PHME file is downloaded, committed, or sent to an external model.

The [official PHME 2022 repository](https://github.com/PHME-Datachallenge/Data-Challenge-2022) says training and validation experiments are split into folders and a password requires challenge registration. It identifies CC BY-NC-SA 4.0. Public repository visibility does not grant us the archive password or clarify whether prize competition use, redistribution, and external AI processing are permitted. Its 2022 challenge registration may no longer be available. We have no supplied password, written permission, or verified archive access.

To reconsider PHME use, verify actual archive access and source terms with the rights holder, including contest use, derivative sharing, public Git hosting, and transmission to Meta or other providers. Keep restricted archives outside Git regardless. Until then, synthetic records must say `SYNTHETIC`; they cannot be described as PHME samples or factory performance evidence.

## PHM Society 2018 alternative — checked 2026-10-27 KST

**Decision: NO-GO for the PCB SPI/AOI/operator chain; conditional candidate for a separate ion-mill equipment case only.** The [official 2018 challenge page](https://phmsociety.org/conference/annual-conference-of-the-phm-society/annual-conference-of-the-prognostics-and-health-management-society-2018-b/phm-data-challenge-6/) describes ion-mill etching tool sensor time series and fault times, not PCB SPI, AOI, or operator confirmation. Its `Lot` field is a wafer identifier in that source; it must not be interpreted as a PCB lot or joined to an unrelated PCB case. The [official description](https://phmsociety.org/wp-content/uploads/2018/05/PHM-Data-Challenge-2018-vFinal-v2_0.pdf) confirms that source scope.

The challenge page links a [Google Drive archive](https://drive.google.com/file/d/15Jx9Scq9FqpIGn8jbAQB_lcHSXvIoPzb/view), but the browser view requires sign-in here. We did not obtain or inspect raw bytes. No explicit dataset license or permission for a new prize contest, public redistribution, or Meta API transmission was found on the official challenge page or PDF. The challenge's historical statement that it was open to professional participants is not a current data-use grant. No 2018 data is included in Git or sent externally.

To use PHM 2018 later, first obtain archive access and written or otherwise explicit rights for this project's use and external processing. If approved, label it as a distinct ion-mill equipment source and evaluate it on its own task. The S1 PCB demonstration remains explicitly synthetic unless a legally usable PCB multi-source dataset is obtained. Do not fabricate SPI/AOI records or connect unrelated manufacturing entities.

## UCI Steel Plates Faults candidate — checked 2026-10-27 KST

The [official UCI page](https://archive.ics.uci.edu/dataset/198/steel+plates+faults) identifies the dataset as CC BY 4.0, names its creators and DOI, and lists a downloadable ZIP. S1 downloaded the ZIP temporarily, verified 1,941 rows with 27 feature and seven one-hot label columns, recorded its hash, then deleted it. No source row entered Git or the app database. Attribution, source link, license link, and modification notice are required when sharing adapted data. See [UCI_STEEL_PLATES.md](UCI_STEEL_PLATES.md) for the field inspection and S1 adapter contract.

This is a separate **real steel fault type** candidate. Its records cannot be joined to fictional PCB panels or used to compute good-vs-bad rates because the source lists defect classes and does not provide normal products. No UCI rows are committed or externally transmitted in S1.


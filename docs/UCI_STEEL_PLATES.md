# UCI Steel Plates Faults — S1 qualification

Official source: https://archive.ics.uci.edu/dataset/198/steel+plates+faults

Citation: Buscema, M., Terzi, S., & Tastle, W. (2010). *Steel Plates Faults* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5J88N

License: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); retain creator/source/license credit and mark modifications when redistributing.

UCI lists 1,941 records, 27 numeric features, no missing values, and seven fault types: `Pastry`, `Z_Scratch`, `K_Scatch`, `Stains`, `Dirtiness`, `Bumps`, `Other_Faults`. On 2026-10-27 KST the ZIP downloaded successfully. Its SHA-256 was `cb8eb9859198b63f053e443513036b401746fa517ef58bd17c846c6741c93919`. We inspected the archive in a temporary local file: `Faults.NNA` has 1,941 rows of 34 whitespace-separated values; `Faults27x7_var` lists the 27 feature and seven label names. Exactly one of the last seven label columns is 1 on every row. The temporary ZIP was deleted after inspection. No UCI record is committed or ingested into the app.

The listed feature fields are `X_Minimum`, `X_Maximum`, `Y_Minimum`, `Y_Maximum`, `Pixels_Areas`, `X_Perimeter`, `Y_Perimeter`, `Sum_of_Luminosity`, `Minimum_of_Luminosity`, `Maximum_of_Luminosity`, `Length_of_Conveyer`, `TypeOfSteel_A300`, `TypeOfSteel_A400`, `Steel_Plate_Thickness`, `Edges_Index`, `Empty_Index`, `Square_Index`, `Outside_X_Index`, `Edges_X_Index`, `Edges_Y_Index`, `Outside_Global_Index`, `LogOfAreas`, `Log_X_Index`, `Log_Y_Index`, `Orientation_Index`, `Luminosity_Index`, `SigmoidOfAreas`. The seven fault columns are class indicators, not predictor features.

The S1 adapter contract is `app/uci_contract.py`: one source row would become a `REAL` steel fault type record with the original row ID, source asset ID, observed defect type, and the 27 original features. A later implementation must parse and validate the values, including the one-hot labels, before import. The source does not provide PCB panel/board/component/pin IDs, SPI/AOI links, timestamps, or known normal products, so none may be invented. This dataset can support fault **type** classification only; it cannot validate good-vs-bad detection or a defect rate. ML and SHAP belong to S4.

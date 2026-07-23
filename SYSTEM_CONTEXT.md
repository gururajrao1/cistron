# VOIDSIGNAL Project State

## Layout

Flat package `voidsignal/` (not `src/`). Version **0.12.0**.

## Phases

1–10 + Option A clinical benchmarking  

**11. 3D Structural Biophysics & Molecular Docking**

- `voidsignal/docking/parser.py` — PDB / PDBQT / SMILES → `Molecule3D`, binding boxes  
- `voidsignal/docking/scoring.py` — empirical ΔG → K_i (RT ln K_i)  
- `voidsignal/docking/kinetics_bridge.py` — docked K_i → `DrugAgent` + k_cat/K_m scales for MassActionRHS

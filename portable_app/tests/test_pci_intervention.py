import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cardio_tagger.pci_intervention import PCIInterventionExtractor, PCIInterventionResult


def test_pci_intervention_extraction_user_case():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "SVG to RPDA:\n"
        "guiding catheter: 6fr ebu3.5 launcher(medtronic)\n"
        "Balloon: sapphire nc 24 3.5 x 15 mm (orbus). 22 atm\n"
        "Drug-eluting stent: synergy Megatron(mr) 4mm x 20mm (boston scientific). 10 atm.\n"
        "Successful angioplasty. Residual stenosis 0%."
    )
    res = extractor.extract(text)
    assert res.intervened_vessels == "SVG TO RPDA"
    assert res.graft_residual_stenosis == "SVG TO RPDA: 0%"
    assert res.rca_residual_stenosis == ""
    assert "SVG TO RPDA: SUCCESSFUL ANGIOPLASTY" in res.success_status
    assert "[GUIDING CATHETER]" in res.devices_used
    assert "6fr ebu3.5 launcher" in res.devices_used.lower()
    assert "[BALLOON]" in res.devices_used
    assert "sapphire nc" in res.devices_used.lower()
    assert "22 atm" in res.devices_used.lower()
    assert "[DRUG-ELUTING STENT]" in res.devices_used
    assert "synergy megatron" in res.devices_used.lower()
    assert "10 atm" in res.devices_used.lower()


def test_pci_intervention_granular_devices_and_blank_residual():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "Prox RCA:\n"
        "Guiding catheter: 6Fr JR4\n"
        "Shockwave (IVL): 3.5 x 12 mm balloon, 80 pulses\n"
        "Rotablator: 1.5 mm burr at 160,000 RPM\n"
        "Cutting balloon: 3.0 x 10 mm Wolverine\n"
        "IVUS: OptiCross pre and post stenting\n"
        "FFR: 0.76 pre-PCI, 0.92 post-PCI\n"
        "Drug-eluting stent: Onyx 3.5 x 24 mm\n"
        "Successful angioplasty.\n\n"
        "D1:\n"
        "Balloon: 2.0 x 12 mm Sapphire\n"
        "Aspiration / Thrombectomy: Export catheter\n"
        "Suboptimal result. Residual stenosis 30%."
    )
    res = extractor.extract(text)
    assert "PROXIMAL RCA" in res.intervened_vessels
    assert "D1" in res.intervened_vessels
    # Blank residual stenosis for Prox RCA because no percentage was given in the report!
    assert res.rca_residual_stenosis == ""
    # D1 residual stenosis
    assert res.lad_residual_stenosis == "D1: 30%"
    # Outcomes
    assert "PROXIMAL RCA: SUCCESSFUL ANGIOPLASTY" in res.success_status
    assert "D1: SUBOPTIMAL RESULT" in res.success_status
    # Granular device tags
    assert "[SHOCKWAVE (IVL)]" in res.devices_used
    assert "[ROTABLATOR]" in res.devices_used
    assert "[CUTTING/SCORING BALLOON]" in res.devices_used
    assert "[IVUS]" in res.devices_used
    assert "[FFR]" in res.devices_used
    assert "[ASPIRATION / THROMBECTOMY]" in res.devices_used


def test_pci_intervention_all_territories_and_branches():
    extractor = PCIInterventionExtractor()
    text = (
        "PERCUTANEOUS CORONARY INTERVENTION:\n"
        "LMCA:\n"
        "Guiding catheter: 6Fr EBU 3.5\n"
        "Drug-eluting stent: Megatron 4.5 x 16 mm\n"
        "Successful stenting. Residual stenosis 0%.\n\n"
        "Proximal LAD:\n"
        "Balloon: NC Trek 3.0 x 12 mm\n"
        "Drug-eluting stent: Xience Sierra 3.0 x 28 mm\n"
        "Successful angioplasty. Residual stenosis <10%.\n\n"
        "OM1:\n"
        "Balloon: Sapphire 2.5 x 15 mm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "RPAV:\n"
        "Balloon: 2.5 x 15 mm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "SVG to RPDA:\n"
        "Drug-eluting stent: Resolute Onyx 3.5 x 18 mm\n"
        "Successful angioplasty. Residual stenosis 0%."
    )
    res = extractor.extract(text)
    assert res.lmca_residual_stenosis == "LMCA: 0%"
    assert res.lad_residual_stenosis == "PROXIMAL LAD: <10%"
    assert res.lcx_residual_stenosis == "OM1: 0%"
    assert res.rca_residual_stenosis == "RPAV: 0%"
    assert res.graft_residual_stenosis == "SVG TO RPDA: 0%"
    assert "LMCA" in res.intervened_vessels
    assert "PROXIMAL LAD" in res.intervened_vessels
    assert "OM1" in res.intervened_vessels
    assert "RPAV" in res.intervened_vessels
    assert "SVG TO RPDA" in res.intervened_vessels


def test_pci_intervention_spelled_out_and_bulleted_vessel_headers():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "Left Anterior Descending Coronary Artery:\n"
        "Guiding catheter: 6Fr EBU 3.5 Launcher\n"
        "Balloon: 3.0 x 15 mm Sapphire NC. 18 atm\n"
        "Drug-eluting stent: 3.5 x 20 mm Synergy. 14 atm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "* Circumflex Coronary Artery (Culprit):\n"
        "Balloon: 2.5 x 15 mm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "Target: Proximal Right Coronary Artery:\n"
        "Drug-eluting stent: 4.0 x 24 mm Onyx\n"
        "Successful angioplasty. Residual stenosis 0%."
    )
    res = extractor.extract(text)
    assert res.lad_residual_stenosis == "LAD: 0%"
    assert res.lcx_residual_stenosis == "LCX: 0%"
    assert res.rca_residual_stenosis == "PROXIMAL RCA: 0%"
    assert "LAD" in res.intervened_vessels
    assert "LCX" in res.intervened_vessels
    assert "PROXIMAL RCA" in res.intervened_vessels


def test_pci_intervention_single_vessel_narrative_without_header():
    extractor = PCIInterventionExtractor()
    text = (
        "PCI INTERVENTION:\n"
        "Successful angioplasty and stenting of proximal LAD.\n"
        "Guiding catheter: 6Fr EBU 3.5 Launcher (Medtronic)\n"
        "Balloon: 3.5 x 15 mm Sapphire NC. 18 atm\n"
        "Drug-eluting stent: 3.5 x 20 mm Synergy Megatron. 14 atm\n"
        "Residual stenosis 0%."
    )
    res = extractor.extract(text)
    assert res.intervened_vessels == "PROXIMAL LAD"
    assert res.lad_residual_stenosis == "PROXIMAL LAD: 0%"
    assert "PROXIMAL LAD: [GUIDING CATHETER]" in res.devices_used


def test_pci_section_parser_delimiters_and_pipeline_fallback():
    from cardio_tagger.sieve_engine import CascadingCardioSieve
    import yaml
    from pathlib import Path
    ont_path = Path(__file__).resolve().parents[1] / "cardio_tagger" / "ontology" / "cardio_concepts.yaml"
    ont = yaml.safe_load(ont_path.read_text(encoding="utf-8"))
    sieve = CascadingCardioSieve(ontology=ont, enable_gliner=False)

    text = (
        "CARDIAC CATHETERIZATION REPORT\n"
        "PATIENT: TAN AH KOW\n\n"
        "PROCEDURE:\n"
        "PCI / INTERVENTION:\n"
        "Left Anterior Descending Coronary Artery:\n"
        "Guiding catheter: 6Fr EBU 3.5 Launcher\n"
        "Balloon: 3.0 x 15 mm Sapphire NC. 18 atm\n"
        "Drug-eluting stent: 3.5 x 20 mm Synergy. 14 atm\n"
        "Successful angioplasty. Residual stenosis 0%.\n\n"
        "CONCLUSION:\n"
        "Successful PCI to LAD."
    )
    res = sieve.evaluate_document("cath_pci_slash.pdf", [text])
    assert res.pci_intervened_vessels == "LAD"
    assert res.pci_lad_residual_stenosis == "LAD: 0%"
    assert "LAD: SUCCESSFUL ANGIOPLASTY" in res.pci_success_status


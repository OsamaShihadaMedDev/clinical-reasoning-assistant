"""Chest pain diagnostic-arm framework (the v1 proof case).

IMPORTANT — clinical content notice: this is a DELIBERATELY SIMPLIFIED,
generalist, teaching-level framework for an MVP proof case. It is NOT an
exhaustive specialist differential, and it is not a diagnostic instrument — it
only drives which history-taking arms get prioritized (CLAUDE.md Section 4). The
risk-factor lists below are the actual clinical content that shifts each arm's
relevance for a specific patient (Section 3). Osama (near-qualified physician) is
the domain owner and will review and correct this content directly.

Shape: a list of `ChestPainArm` dataclasses kept as plain, auditable data — one
arm per entry, each carrying the risk factors that RAISE its relevance and a
`red_flag` marker. `red_flag` is intentionally NOT consumed yet: the data
contracts don't carry it, and the Triage Agent does not use it (it scores
relevance only). It is recorded here as a marker for the FUTURE Prioritization/
Red-Flag agent, which must know which arms are time-critical and must never be
silently allowed to drop in priority.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChestPainArm:
    # Arm label as the clinician thinks of it; this becomes DiagnosticArm.name.
    name: str
    # Plain-language factors that RAISE this arm's relevance for a given patient.
    # These are what the Triage Agent weighs against the patient context.
    risk_factors: list[str]
    # True = time-critical / life-threatening "can't-miss" arm. Marker only for now
    # (see module docstring) — not fed to triage, reserved for the future
    # Prioritization/Red-Flag agent.
    red_flag: bool


CHEST_PAIN_ARMS: list[ChestPainArm] = [
    ChestPainArm(
        name="Cardiac (ACS / Ischemic)",
        risk_factors=[
            "Age over ~40 in men / ~50 in women (risk rises with age)",
            "Male sex",
            "Current or past smoking",
            "Diabetes mellitus",
            "Hypertension",
            "High cholesterol / dyslipidemia",
            "Family history of premature coronary artery disease",
            "Known coronary disease, prior MI, prior stent/CABG",
            "Pain brought on by exertion and relieved by rest",
            "Pressure / heaviness / tightness quality (rather than sharp)",
            "Radiation to the left arm, both arms, or jaw",
            "Associated sweating, nausea, or breathlessness",
        ],
        red_flag=True,
    ),
    ChestPainArm(
        name="Aortic Dissection",
        risk_factors=[
            "Sudden, severe pain that is maximal at onset",
            "Tearing or ripping quality",
            "Pain radiating to the back / between the shoulder blades",
            "Long-standing or poorly controlled hypertension",
            "Connective tissue disease (Marfan, Ehlers-Danlos)",
            "Known aortic aneurysm or bicuspid aortic valve",
            "Blood pressure or pulse difference between the two arms",
            "Cocaine use",
            "Older age (~50-70), male",
        ],
        red_flag=True,
    ),
    ChestPainArm(
        name="Pulmonary Embolism",
        risk_factors=[
            "Pleuritic pain (worse on deep inspiration)",
            "Sudden breathlessness",
            "Fast heart rate",
            "Recent immobility, long-haul travel, or surgery",
            "Active cancer",
            "Previous DVT/PE or known clotting disorder",
            "Unilateral leg swelling or calf pain (DVT)",
            "Estrogen use (oral contraceptive / HRT), pregnancy or postpartum",
            "Coughing up blood",
            "Low oxygen saturations",
        ],
        red_flag=True,
    ),
    ChestPainArm(
        name="Pneumothorax",
        risk_factors=[
            "Sudden pleuritic pain with acute breathlessness",
            "Tall, thin, young male (primary spontaneous)",
            "Smoking",
            "Underlying lung disease such as COPD or asthma (secondary)",
            "Recent chest trauma or chest procedure",
            "Connective tissue disease (Marfan)",
            "Tension features: low blood pressure, tracheal deviation, distended neck veins",
        ],
        red_flag=True,
    ),
    ChestPainArm(
        name="GERD / Esophageal",
        risk_factors=[
            "Burning retrosternal pain",
            "Related to meals, or worse lying flat / at night",
            "Relieved by antacids",
            "Acid regurgitation, sour taste, or water brash",
            "Known reflux or peptic ulcer history",
            "No relationship to exertion",
            "Difficulty swallowing (esophageal spasm)",
        ],
        red_flag=False,
    ),
    ChestPainArm(
        name="Musculoskeletal",
        risk_factors=[
            "Pain reproducible / tender on pressing the chest wall",
            "Worse with movement, posture, or twisting",
            "Recent trauma, heavy lifting, new exercise, or persistent cough",
            "Well-localized, easy to point to",
            "Younger patient with no cardiac risk factors",
        ],
        red_flag=False,
    ),
    ChestPainArm(
        name="Panic / Anxiety",
        risk_factors=[
            "Younger patient",
            "Known anxiety or panic disorder",
            "Palpitations, tingling, or a sense of impending doom",
            "Hyperventilation",
            "Triggered by stress",
            "Atypical, shifting pain unrelated to exertion",
        ],
        red_flag=False,
    ),
]

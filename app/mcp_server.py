import datetime
import json
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MedCompanion")

LOG_FILE = "/Users/viveknarvariya/Desktop/ADK.workspace/med-companion/care_logs.json"

# Simulated clinical database
DRUG_INTERACTIONS = {
    ("aspirin", "warfarin"): "Bleeding hazard. Concomitant use increases risk of gastrointestinal or systemic hemorrhage.",
    ("ibuprofen", "lisinopril"): "Kidney hazard / efficacy loss. NSAIDs can decrease antihypertensive effect and increase acute kidney injury risk.",
    ("simvastatin", "amiodarone"): "Muscle toxicity. Amiodarone increases simvastatin blood levels, raising the risk of myopathy or rhabdomyolysis.",
    ("sildenafil", "nitroglycerin"): "Severe hypotension hazard. Concomitant use can lead to life-threatening drops in blood pressure."
}

DRUG_GUIDELINES = {
    "lisinopril": {
        "class": "ACE Inhibitor",
        "guideline": "Take once daily, usually at the same time each day. May be taken with or without food.",
        "side_effects": "Dry cough, dizziness, headache, high potassium levels.",
        "warnings": "Avoid potassium supplements or salt substitutes containing potassium without consulting doctor. Do not take if pregnant."
    },
    "metformin": {
        "class": "Biguanide (Antidiabetic)",
        "guideline": "Take with meals to reduce stomach upset. Swallow extended-release tablets whole.",
        "side_effects": "Nausea, diarrhea, metallic taste, abdominal bloating.",
        "warnings": "Risk of lactic acidosis (rare but serious). Limit alcohol intake."
    },
    "atorvastatin": {
        "class": "HMG-CoA Reductase Inhibitor (Statins)",
        "guideline": "Take once daily at any time of day, with or without food.",
        "side_effects": "Muscle aches, headache, mild nausea, joint pain.",
        "warnings": "Avoid large amounts of grapefruit juice (can increase drug levels). Contact doctor immediately if unexplained muscle pain occurs."
    },
    "albuterol": {
        "class": "Bronchodilator (Beta-2 Agonist)",
        "guideline": "Inhale 2 puffs every 4 to 6 hours as needed for shortness of breath or wheezing.",
        "side_effects": "Tremor, nervousness, rapid heart rate, headache.",
        "warnings": "Contact doctor if breathing issues worsen rapidly or if you need to use the inhaler more than prescribed."
    }
}

@mcp.tool()
def check_drug_interactions(drugs: list[str]) -> str:
    """Checks for known clinical drug-drug interactions between listed medications.
    
    Args:
        drugs: A list of drug names to check (e.g. ['aspirin', 'warfarin']).
    """
    normalized_drugs = [d.strip().lower() for d in drugs]
    found_interactions = []
    
    # Check pairs
    for i in range(len(normalized_drugs)):
        for j in range(i + 1, len(normalized_drugs)):
            d1, d2 = normalized_drugs[i], normalized_drugs[j]
            # Check dictionary keys in either order
            pair1 = (d1, d2)
            pair2 = (d2, d1)
            
            if pair1 in DRUG_INTERACTIONS:
                found_interactions.append(f"⚠️ Interaction [{d1} + {d2}]: {DRUG_INTERACTIONS[pair1]}")
            elif pair2 in DRUG_INTERACTIONS:
                found_interactions.append(f"⚠️ Interaction [{d2} + {d1}]: {DRUG_INTERACTIONS[pair2]}")
                
    if found_interactions:
        return "\n".join(found_interactions)
    return "✅ No common drug interactions found in the database for the provided medications."

@mcp.tool()
def get_medication_guidelines(drug: str) -> str:
    """Retrieves patient-centric dosage, schedule guidelines, and side effects for a medication.
    
    Args:
        drug: The name of the medication (e.g. 'lisinopril', 'metformin').
    """
    normalized_drug = drug.strip().lower()
    if normalized_drug in DRUG_GUIDELINES:
        info = DRUG_GUIDELINES[normalized_drug]
        return (
            f"**Medication**: {drug.capitalize()}\n"
            f"**Drug Class**: {info['class']}\n"
            f"**Recommended Intake**: {info['guideline']}\n"
            f"**Common Side Effects**: {info['side_effects']}\n"
            f"**Critical Warnings**: {info['warnings']}"
        )
    return f"ℹ️ Medication '{drug}' not found in the local guidelines database. Please check spelling or consult your provider."

@mcp.tool()
def log_medication_intake(drug: str, dose: str, time: str) -> str:
    """Appends an intake event record to the patient care log file.
    
    Args:
        drug: Name of the medication.
        dose: Dosage amount (e.g. '50mg', '1 pill').
        time: Time when the medication was taken (e.g. '9:00 AM', 'now').
    """
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
        except Exception:
            pass
            
    logs.append({
        "drug": drug,
        "dose": dose,
        "time": time,
        "logged_at": datetime.datetime.now().isoformat()
    })
    
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
        return f"Successfully logged intake of {drug} ({dose}) at {time}."
    except Exception as e:
        return f"Error writing to care log file: {str(e)}"

@mcp.tool()
def get_care_logs() -> str:
    """Reads and returns all logged medication intake records from the patient care logs."""
    if not os.path.exists(LOG_FILE):
        return "No care logs found. The log file is empty."
        
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
        if not logs:
            return "No care logs found. The log file is empty."
            
        lines = ["--- Care Logs ---"]
        for entry in logs:
            lines.append(f"- [{entry['logged_at'][:16]}] Took {entry['dose']} of {entry['drug']} at {entry['time']}.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading care logs: {str(e)}"

if __name__ == "__main__":
    mcp.run()

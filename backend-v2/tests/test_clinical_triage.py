"""Red-flag triage rules: what must escalate, and what must not."""

import pytest

from clinical_triage import (
    assess,
    emergency_number,
    max_urgency,
    urgency_rank,
)

EMERGENCIES = [
    # Mental health
    "I want to kill myself",
    "I don't want to live anymore and have pills saved",
    "she keeps saying she wants to die",
    "I have been cutting myself",
    # Poisoning / overdose
    "I took 30 paracetamol tablets",
    "my son swallowed bleach",
    "I think I overdosed on my sleeping pills",
    # Breathing
    "my baby is not breathing",
    "I can't breathe",
    "he cannot breathe properly and his lips are blue",
    "no chest pain and can't breathe",
    # Cardiac
    "crushing chest pressure spreading to my left arm",
    "I have chest pain",
    "Sudden crushing chest pain spreading to my left arm and I can't breathe",
    # Stroke
    "his face is drooping on one side and his arm is weak",
    "my mother suddenly cannot speak",
    "slurred speech since this morning",
    # Consciousness / seizures
    "my father collapsed and is unresponsive",
    "the baby is having a seizure",
    "she passed out and won't wake up",
    # Bleeding
    "I am vomiting blood",
    "heavy bleeding that won't stop",
    # Infection danger signs
    "temperature 40 degrees and stiff neck",
    "fever and stiff neck since yesterday",
    # Children (WHO IMCI danger signs) and young infants
    "My 2 month old baby has a fever and is very sleepy",
    "my 3 week old has a fever",
    "my child is vomiting everything and is very sleepy",
    "my daughter is not able to drink anything",
    # Pregnancy danger signs
    "I am 30 weeks pregnant and bleeding",
    "pregnant with a severe headache and blurred vision",
    # Amharic
    "የደረት ሕመም አለኝ እና መተንፈስ አልችልም",
    "ራሴን ማጥፋት እፈልጋለሁ",
    "አባቴ ራሱን ሳተ",
]

URGENT = [
    "My child has had a fever of 39C for 3 days and is not eating",
    "high fever since last night",
    "temperature 39.5 C",
    "fever of 103F",
    "I can't keep any fluids down",
    "bloody diarrhea since yesterday",
    "worst headache of my life",
]

NOT_EMERGENCY = [
    "I have had a mild headache and runny nose for 2 days",
    "no chest pain, just a mild cold",
    "I don't have chest pain or difficulty breathing, just a sore throat",
    "my 40 year old husband has a cough",
    "I took 2 tablets of paracetamol for a headache",
    "I take 500 mg tablets of metformin",
    "I think I have food poisoning, mild diarrhea",
    "My skin is itchy",
    "normal temperature, mild sore throat",
]


@pytest.mark.parametrize("text", EMERGENCIES)
def test_emergencies_escalate(text):
    result = assess(text)
    assert result.urgency == "emergency", (text, result.reasons)


@pytest.mark.parametrize("text", URGENT)
def test_urgent_cases_are_at_least_urgent(text):
    result = assess(text)
    assert urgency_rank(result.urgency) >= urgency_rank("urgent"), (text, result.reasons)


@pytest.mark.parametrize("text", NOT_EMERGENCY)
def test_everyday_messages_are_not_emergencies(text):
    result = assess(text)
    assert result.urgency != "emergency", (text, result.reasons)


class TestPatientContext:
    def test_infant_age_with_fever_is_emergency(self):
        assert assess("fever since this morning", age_years=0).urgency == "emergency"

    def test_older_adult_with_fever_is_urgent(self):
        assert assess("I have a fever", age_years=82).urgency == "urgent"

    def test_pregnancy_flag_with_bleeding_is_emergency(self):
        assert assess("some bleeding today", pregnant=True).urgency == "emergency"

    def test_adult_mild_cold_stays_routine(self):
        assert assess("runny nose and sneezing", age_years=30).urgency == "routine"

    def test_child_with_fever_sees_a_doctor_soon(self):
        result = assess("fever since yesterday", age_years=3)
        assert urgency_rank(result.urgency) >= urgency_rank("see_doctor_soon")


class TestUrgencyOrdering:
    def test_max_never_lowers(self):
        assert max_urgency("emergency", "routine") == "emergency"
        assert max_urgency("routine", "urgent") == "urgent"
        assert max_urgency("self_care", "see_doctor_soon") == "see_doctor_soon"

    def test_unknown_labels_are_not_reassuring(self):
        assert max_urgency("EMERGENCY - call now") == "emergency"
        assert max_urgency("critical") == "emergency"
        assert max_urgency("something odd") == "see_doctor_soon"


class TestEmergencyNumbers:
    @pytest.mark.parametrize("location", ["Mekelle, Ethiopia", "Addis Ababa, ET", "ethiopia"])
    def test_ethiopia(self, location):
        assert emergency_number(location).startswith("907")

    def test_city_names_do_not_match_country_codes(self):
        # "Mekelle" contains "ke" (Kenya) and used to get Kenya's number.
        assert emergency_number("Mekelle") != emergency_number("Kenya")

    def test_kenya(self):
        assert emergency_number("Nairobi, Kenya") == "999 or 112"

    def test_unknown_location_defaults_safely(self):
        assert "907" in emergency_number(None)


@pytest.mark.parametrize(
    "text",
    [
        "no idea why I can't breathe",
        "no fever, my baby can't breathe",
        "not sure what is happening but he collapsed",
        "my son is not responding",
    ],
)
def test_negation_does_not_hide_emergencies(text):
    assert assess(text).urgency == "emergency", text

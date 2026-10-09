"""Pre-loaded areas, their seasons, flood events and the authorities a citizen can write to.

Any place in India or Nepal can be checked on demand; these areas are analysed in full at deploy time
(every water body, the time machine, flood-event radar layers). Authority entries are roles that exist by law
or by government order; letters are addressed to the role, and the citizen chooses where to send them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CPGRAMS = {"id": "cpgrams", "kind": "grievance", "name": "Centralised Public Grievance Redress and Monitoring System (CPGRAMS)",
           "url": "https://pgportal.gov.in", "how": "Lodge the grievance online and attach the signed dossier PDF."}
HELLO_SARKAR = {"id": "hello-sarkar", "kind": "grievance", "name": "Hello Sarkar, Office of the Prime Minister and Council of Ministers",
                "url": "https://hellosarkar.gov.np", "how": "Call 1111 or lodge the complaint online; attach the dossier PDF."}
NGT_SOUTH = {"id": "ngt-south", "kind": "court", "name": "National Green Tribunal, Southern Zone Bench (Chennai)",
             "how": "Escalation route if authorities do not act; the dossier can support an application."}
NGT_PRINCIPAL = {"id": "ngt-principal", "kind": "court", "name": "National Green Tribunal, Principal Bench (New Delhi)",
                 "how": "Escalation route if authorities do not act; the dossier can support an application."}
NGT_EAST = {"id": "ngt-east", "kind": "court", "name": "National Green Tribunal, Eastern Zone Bench (Kolkata)",
            "how": "Escalation route if authorities do not act; the dossier can support an application."}

LAW_IN = ["Wetlands (Conservation and Management) Rules, 2017",
          "Supreme Court of India, Jagpal Singh v. State of Punjab (2011): village ponds and common lands must be "
          "restored and kept free of encroachment"]
LAW_NP = ["Environment Protection Act, 2076 (2019)"]


@dataclass
class Area:
    id: str
    names: dict
    country: str
    state: str
    lang: str
    bbox: list
    zoom: float
    look: tuple            # post-monsoon window (MM-DD, MM-DD) used to judge how full water bodies get
    rain: tuple            # months whose rain fills them
    min_ha: float = 2.0
    events: list = field(default_factory=list)
    story: str = ""
    authorities: list = field(default_factory=list)
    laws: list = field(default_factory=list)
    flood2026: bool = False

    @property
    def center(self) -> list:
        w, s, e, n = self.bbox
        return [round((w + e) / 2, 5), round((s + n) / 2, 5)]

    def public(self) -> dict:
        return {"id": self.id, "names": self.names, "country": self.country, "state": self.state, "lang": self.lang,
                "bbox": self.bbox, "center": self.center, "zoom": self.zoom, "events": self.events,
                "story": self.story, "flood2026": self.flood2026}


AREAS: dict[str, Area] = {a.id: a for a in [
    Area("bengaluru", {"en": "Bengaluru", "kn": "ಬೆಂಗಳೂರು", "hi": "बेंगलुरु"}, "IN", "Karnataka", "kn",
         [77.45, 12.83, 77.80, 13.15], 11.2, ("10-15", "02-28"), (6, 7, 8, 9, 10),
         events=[{"date": "2022-09-05", "title": "Bengaluru floods, 5 Sep 2022",
                  "detail": "Heavy rain on 4-5 September 2022 flooded Bellandur, Mahadevapura and Sarjapur Road."}],
         story="A city built on a chain of tanks (kere) linked by storm channels (rajakaluve). Where the tanks and "
               "channels were built over, the rain still goes there.",
         authorities=[
             {"id": "gba", "kind": "city", "name": "Greater Bengaluru Authority (GBA) and your city corporation"},
             {"id": "ktcda", "kind": "lakes", "name": "Karnataka Tank Conservation and Development Authority (KTCDA)"},
             {"id": "dc-bu", "kind": "district", "name": "Deputy Commissioner, Bengaluru Urban district"},
             {"id": "kswa", "kind": "wetland", "name": "Karnataka State Wetland Authority"},
             CPGRAMS, NGT_SOUTH],
         laws=LAW_IN + ["Karnataka Tank Conservation and Development Authority Act, 2014"]),
    Area("chennai", {"en": "Chennai", "ta": "சென்னை", "hi": "चेन्नई"}, "IN", "Tamil Nadu", "ta",
         [80.05, 12.82, 80.33, 13.25], 10.8, ("12-20", "03-31"), (6, 7, 8, 9, 10, 11, 12),
         events=[{"date": "2015-12-06", "title": "Chennai floods, December 2015",
                  "detail": "Record rain on 1-2 December 2015 flooded large parts of the city along the Adyar and around Pallikaranai."}],
         story="Chennai's eris (tanks) and the Pallikaranai marsh used to hold the north-east monsoon. Much of the "
               "marsh and many eris now lie under roads, IT parks and housing.",
         authorities=[
             {"id": "gcc", "kind": "city", "name": "Greater Chennai Corporation"},
             {"id": "tn-wrd", "kind": "lakes", "name": "Water Resources Department, Government of Tamil Nadu (Chennai Region)"},
             {"id": "collector", "kind": "district", "name": "District Collector (Chennai, Chengalpattu, Kancheepuram or Tiruvallur, by location)"},
             {"id": "tnswa", "kind": "wetland", "name": "Tamil Nadu State Wetland Authority"},
             CPGRAMS, NGT_SOUTH],
         laws=LAW_IN + ["Tamil Nadu Protection of Tanks and Eviction of Encroachment Act, 2007"]),
    Area("hyderabad", {"en": "Hyderabad", "te": "హైదరాబాద్", "hi": "हैदराबाद"}, "IN", "Telangana", "te",
         [78.28, 17.22, 78.65, 17.56], 10.9, ("10-20", "02-28"), (6, 7, 8, 9, 10),
         events=[{"date": "2020-10-21", "title": "Hyderabad floods, October 2020",
                  "detail": "Extreme rain on 13-14 and 17-18 October 2020 breached tanks and flooded colonies in the old city and LB Nagar."}],
         story="Hyderabad's cheruvus and kuntas were built as a cascade. Encroached full-tank levels and broken "
               "links between tanks turn heavy rain into floods.",
         authorities=[
             {"id": "hydraa", "kind": "lakes", "name": "HYDRAA - Hyderabad Disaster Response and Asset Protection Agency"},
             {"id": "ghmc", "kind": "city", "name": "Greater Hyderabad Municipal Corporation (GHMC)"},
             {"id": "hmda", "kind": "lakes", "name": "Hyderabad Metropolitan Development Authority (HMDA), Lakes Division"},
             {"id": "collector", "kind": "district", "name": "District Collector (Hyderabad, Ranga Reddy, Medchal-Malkajgiri or Sangareddy, by location)"},
             {"id": "tsswa", "kind": "wetland", "name": "Telangana State Wetland Authority"},
             CPGRAMS, NGT_SOUTH],
         laws=LAW_IN),
    Area("delhi-ncr", {"en": "Delhi-NCR", "hi": "दिल्ली-एनसीआर"}, "IN", "Delhi / Haryana / Uttar Pradesh", "hi",
         [76.90, 28.38, 77.45, 28.80], 10.4, ("10-01", "02-28"), (6, 7, 8, 9),
         events=[{"date": "2023-07-12", "title": "Yamuna floods, July 2023",
                  "detail": "The Yamuna rose past its highest recorded level on 12 July 2023, peaked on 13 July and flooded the floodplain and parts of central Delhi."}],
         story="The Yamuna floodplain, Delhi's johads and Gurugram's ponds once stored monsoon water. In Gurugram, the "
               "municipal survey found 65 of 181 recorded ponds encroached (2025).",
         authorities=[
             {"id": "wad", "kind": "wetland", "name": "Wetland Authority of Delhi"},
             {"id": "dda", "kind": "lakes", "name": "Delhi Development Authority (Yamuna floodplain)"},
             {"id": "ifc", "kind": "lakes", "name": "Irrigation and Flood Control Department, Government of NCT of Delhi"},
             {"id": "mcg", "kind": "city", "name": "Municipal Corporation of Gurugram / Municipal Corporation of Delhi (by location)"},
             {"id": "hpwwma", "kind": "lakes", "name": "Haryana Pond and Waste Water Management Authority"},
             {"id": "dm", "kind": "district", "name": "District Magistrate / Deputy Commissioner (by location)"},
             CPGRAMS, NGT_PRINCIPAL],
         laws=LAW_IN),
    Area("kochi", {"en": "Kochi", "ml": "കൊച്ചി", "hi": "कोच्चि"}, "IN", "Kerala", "ml",
         [76.18, 9.88, 76.42, 10.20], 10.9, ("12-01", "03-31"), (6, 7, 8, 9, 10, 11), min_ha=1.0, flood2026=True,
         events=[{"date": "2026-08-10", "title": "Kerala floods, August 2026",
                  "detail": "Heavy rain from 1 August 2026 flooded low-lying parts of Kerala, including parts of Ernakulam district; Kottayam and Pathanamthitta stayed waterlogged for days."},
                 {"date": "2018-08-21", "title": "Kerala floods, August 2018",
                  "detail": "The August 2018 floods inundated Aluva and the Periyar banks north of Kochi."}],
         story="Kochi's paddy wetlands, canals and backwaters were its sponge. Reclaimed wetlands are where the water "
               "stands longest.",
         authorities=[
             {"id": "kmc", "kind": "city", "name": "Kochi Municipal Corporation"},
             {"id": "collector-ekm", "kind": "district", "name": "District Collector, Ernakulam"},
             {"id": "kswa-kl", "kind": "wetland", "name": "Kerala State Wetland Authority"},
             {"id": "irrigation-kl", "kind": "lakes", "name": "Irrigation Department, Government of Kerala"},
             CPGRAMS, NGT_SOUTH],
         laws=LAW_IN + ["Kerala Conservation of Paddy Land and Wetland Act, 2008"]),
    Area("sivasagar", {"en": "Sivasagar", "as": "শিৱসাগৰ", "hi": "शिवसागर"}, "IN", "Assam", "as",
         [94.50, 26.88, 94.75, 27.08], 11.0, ("11-01", "02-28"), (5, 6, 7, 8, 9), min_ha=1.0, flood2026=True,
         events=[{"date": "2026-08-03", "title": "Assam floods, July-August 2026",
                  "detail": "Heavy rain from 18 July 2026 pushed the Dikhow, Disang and other rivers above danger level; by 20 July the Dikhow had passed its highest recorded flood level, flooding Sivasagar, Charaideo, Jorhat and Golaghat."}],
         story="The Ahom-era tanks of Sivasagar still stand. The low ground around them along the Dikhow is where "
               "flood water spreads; radar shows where it went in 2026.",
         authorities=[
             {"id": "dc-siv", "kind": "district", "name": "Deputy Commissioner, Sivasagar"},
             {"id": "smb", "kind": "city", "name": "Sivasagar Municipal Board"},
             {"id": "wrd-as", "kind": "lakes", "name": "Water Resources Department, Government of Assam"},
             {"id": "asdma", "kind": "disaster", "name": "Assam State Disaster Management Authority"},
             CPGRAMS, NGT_EAST],
         laws=LAW_IN),
    Area("bhadrak", {"en": "Bhadrak", "or": "ଭଦ୍ରକ", "hi": "भद्रक"}, "IN", "Odisha", "or",
         [86.38, 20.95, 86.62, 21.15], 11.0, ("11-01", "03-15"), (6, 7, 8, 9, 10), min_ha=1.0, flood2026=True,
         events=[{"date": "2026-08-04", "title": "Odisha floods, July-August 2026",
                  "detail": "In late July 2026 Bhadrak was Odisha's worst-affected district: the Baitarani ran above danger level and more than 4 lakh people were affected."}],
         story="A delta district between the Baitarani and Salandi. Village ponds and old channels decide where "
               "flood water lingers after an embankment breach.",
         authorities=[
             {"id": "collector-bdk", "kind": "district", "name": "Collector and District Magistrate, Bhadrak"},
             {"id": "bmun", "kind": "city", "name": "Bhadrak Municipality"},
             {"id": "dowr-or", "kind": "lakes", "name": "Department of Water Resources, Government of Odisha"},
             {"id": "osdma", "kind": "disaster", "name": "Odisha State Disaster Management Authority"},
             CPGRAMS, NGT_EAST],
         laws=LAW_IN),
    Area("kathmandu", {"en": "Kathmandu Valley", "ne": "काठमाडौं उपत्यका", "hi": "काठमांडू घाटी"}, "NP", "Bagmati Province", "ne",
         [85.22, 27.60, 85.48, 27.79], 11.2, ("10-15", "02-28"), (6, 7, 8, 9), min_ha=0.5,
         events=[{"date": "2024-09-27", "title": "Kathmandu Valley floods, September 2024",
                  "detail": "Record rain on 27-28 September 2024 sent the Bagmati, Nakkhu and Balkhu into settlements on their banks."}],
         story="The valley's rivers have been squeezed by settlements on their banks, and the 2024 floods went where "
               "the rivers used to run. Most of its old ponds (pokhari) are smaller than a satellite pixel, so here "
               "place checks and flood radar say more than the lake list.",
         authorities=[
             {"id": "metro", "kind": "city", "name": "Kathmandu / Lalitpur Metropolitan City or Bhaktapur Municipality (by location)"},
             {"id": "dao", "kind": "district", "name": "District Administration Office (by district)"},
             {"id": "hpcidbc", "kind": "lakes", "name": "High Powered Committee for Integrated Development of the Bagmati Civilization"},
             {"id": "dowri", "kind": "lakes", "name": "Department of Water Resources and Irrigation"},
             HELLO_SARKAR],
         laws=LAW_NP),
    Area("butwal", {"en": "Butwal", "ne": "बुटवल", "hi": "बुटवल"}, "NP", "Lumbini Province", "ne",
         [83.38, 27.62, 83.52, 27.74], 12.0, ("10-15", "02-28"), (6, 7, 8, 9), min_ha=0.5, flood2026=True,
         events=[{"date": "2026-09-29", "title": "Tinau floods, September 2026",
                  "detail": "On the night of 26 September 2026 the Tinau rose above its danger level and swept away houses on its bank."}],
         story="Butwal grew down the Tinau's floodplain. In September 2026 the river took back houses built on its bank.",
         authorities=[
             {"id": "butwal-smc", "kind": "city", "name": "Butwal Sub-Metropolitan City"},
             {"id": "dao-rup", "kind": "district", "name": "District Administration Office, Rupandehi"},
             {"id": "dowri", "kind": "lakes", "name": "Department of Water Resources and Irrigation (river training)"},
             HELLO_SARKAR],
         laws=LAW_NP),
]}

UI_LANGUAGES = ("en", "hi", "kn", "ta", "te", "ml", "ne")


def area_for(lat: float, lon: float) -> Area | None:
    for a in AREAS.values():
        w, s, e, n = a.bbox
        if w <= lon <= e and s <= lat <= n:
            return a
    return None


def default_authorities(country: str) -> list:
    if country == "NP":
        return [{"id": "municipality", "kind": "city", "name": "Your Metropolitan / Municipal office"},
                {"id": "dao", "kind": "district", "name": "District Administration Office"}, HELLO_SARKAR]
    return [{"id": "municipal", "kind": "city", "name": "Commissioner, your municipal corporation or council"},
            {"id": "collector", "kind": "district", "name": "District Collector / Deputy Commissioner"},
            {"id": "swa", "kind": "wetland", "name": "Member Secretary, your State Wetland Authority"}, CPGRAMS]

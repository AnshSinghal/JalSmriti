"""Signed place report PDF: renders in all seven reader languages, on one to three A4 pages, with or without the
optional sections, and survives broken pictures and place names in another script."""
import io
import random
import re

import pytest

from jalsmriti import report_pdf

LANGS = ["en", "hi", "kn", "ta", "te", "ml", "ne"]


def _f(template: str, **v) -> str:
    for k, x in v.items():
        template = template.replace("{" + k + "}", str(x))
    return template


# Strings marked "dict" are copied verbatim from the website dictionaries (web/src/i18n/*.ts); the rest are labels the
# report adds, translated by hand for the test.
T = {
    "en": {
        "title": "Bellandur, Bengaluru", "lat": 12.9352, "lon": 77.6807, "tier": "strong", "index": 79,
        "docTitle": "JalSmriti place report", "signedNote": "Digitally signed: check it on the last page",
        "made": "Prepared 11 Oct 2026, 09:12 IST", "checked": "Checked on 10 Oct 2026",
        "coords": "12.93520 N, 77.68070 E",
        "memoryTitle": "What this place remembers",                                                    # dict
        "findings": "What the records show",                                                           # dict
        "timelapse": "The same spot through the years",                                               # dict
        "radar": "Monsoon radar sightings",                                                            # dict
        "heat": "Summer heat", "reports": "Standing water reported nearby",
        "actions": "What you can do",                                                                  # dict
        "questions": "Questions to ask the owner or seller",
        "limits": "Honest about limits",                                                               # dict
        "verification": "Evidence you can check yourself",                                             # dict
        "payload": "Content fingerprint",                                                              # dict
        "key": "Signing key fingerprint",                                                              # dict
        "check": "Verify the signature",                                                               # dict
        "checkHow": "When the dossier was finished, JalSmriti wrote down its fingerprints and the time, then signed that statement with an ECDSA P-256 key that never leaves AWS KMS. Your browser downloads the public key and checks the signature itself with the Web Crypto API, so you do not have to take this server's word for it.",  # dict
        "footer": "JalSmriti is a public-interest decision aid. Satellite outlines are approximate and are not a land survey.",  # dict
        "page": "Page {n} of {total}",
        "tierLabel": "Strong water memory", "indexLabel": _f("{n} of 100", n=79),                     # dict
        "explain": "Compared with ordinary built-up places in four Indian cities. It describes history and terrain; it is not a flood forecast.",  # dict
        "validation": "In our test, 15% of localities reported flooded had little water memory, against 43% of ordinary built-up places.",  # dict
        "f": [(_f("Satellites saw water on this very spot in {pct}% of looks between 1984 and 2020.", pct=62), "high"),  # dict
              (_f("Within 2 km, {ha} ha of old water-body beds are now built over.", ha=21.4), "high"),                   # dict
              (_f("Radar saw unusual standing water within 300 m on {date} ({ha} ha).", date="18 Aug 2025", ha=1.3), "high"),  # dict
              (_f("{ha} ha of water that existed within 300 m has disappeared since 1984.", ha=4.2), "medium"),          # dict
              (_f("The ground within 300 m forms a bowl up to {m} m deep where rain can pond.", m=2.1), "medium"),      # dict
              ("Part of this place sits less than 1 m above the nearest natural drainage line.", "medium"),             # dict
              (_f("The nearest historic water body is {m} m away.", m=180), "info")],                                  # dict
        "radarSentence": _f("Sightings: {n}, in {scenes} monsoon passes", n=3, scenes=41),                              # dict
        "radarDates": ["5 Sep 2022", "12 Oct 2024", "18 Aug 2025"],
        "heatLines": ["The ground here reached 46 °C on 14 May 2026, among the hottest tenth of the city.",
                      "Tree cover within 300 m: 6%. Shade and cross-ventilation matter in summer."],
        "heatScale": "25 °C to 50 °C",
        "reportSentence": "People nearby reported standing water 2 times since June 2026.",
        "reportItems": ["12 Sep 2026, 350 m away: knee-deep water on the main road for a day",
                        "28 Jul 2026, 600 m away: water in a basement car park"],
        "actionsTitle": "This week, before you sign anything",
        "actionItems": ["Buying or renting? Ask for the revenue record of the land and whether it was ever a tank or lake bed, and check the drain and lake buffer zones in the local master plan.",  # dict
                        "Visit the day after heavy rain and look for water lines on compound walls and gates.",
                        "Ask two neighbours how high the water came in the last monsoon.",
                        "Living here? Keep drains clear before the monsoon and join or start a group for the nearest lake."],  # dict
        "qs": ["Was this land ever a tank, lake bed or drain? May I see the revenue record?",
                      "Has water entered the building, the basement or the parking in any monsoon? How deep, and for how long?",
                      "Where does rain from the road and the plot drain to, and who clears that drain?",
                      "Is the plot inside a lake or drain buffer zone in the master plan?"],
        "lims": ["Pixels are 10 to 30 m.", "Radar cannot see between tall buildings.",                           # dict
                   "A water memory is history, not a flood forecast.",                                              # dict
                   "Satellite outlines are approximate and are not a land survey."],                                # dict
        "sources": "Landsat 4-9 and Sentinel-2 from 1987, Sentinel-1 radar, JRC Global Surface Water, Impact Observatory land cover, ESA WorldCover, Copernicus elevation, NASA POWER rainfall, OpenStreetMap and GeoNames names.",  # dict
    },
    "hi": {
        "title": "बेल्लंदूर, बेंगलुरु", "lat": 12.9352, "lon": 77.6807, "tier": "strong", "index": 79,
        "docTitle": "जलस्मृति स्थान रिपोर्ट", "signedNote": "डिजिटल हस्ताक्षरित: आख़िरी पन्ने पर जाँचें",
        "made": "11 अक्टू 2026, 09:12 IST को तैयार",
        "checked": _f("{date} को जाँचा गया", date="10 अक्टू 2026"),                                       # dict
        "coords": _f("{lat} उत्तर, {lon} पूर्व", lat="12.93520", lon="77.68070"),                          # dict
        "memoryTitle": "इस जगह को क्या याद है", "findings": "रिकॉर्ड क्या दिखाते हैं",                    # dict
        "timelapse": "साल-दर-साल वही जगह", "radar": "मानसून में रडार से दिखा पानी",                       # dict
        "heat": "गर्मी", "reports": "आस-पास जमा पानी की खबरें",
        "actions": "आप क्या कर सकते हैं",                                                                # dict
        "questions": "मालिक या विक्रेता से पूछें",
        "limits": "सीमाओं पर ईमानदारी", "verification": "ऐसे सबूत जिन्हें आप खुद जाँच सकते हैं",            # dict
        "payload": "सामग्री का फ़िंगरप्रिंट", "key": "हस्ताक्षर कुंजी का फ़िंगरप्रिंट",                        # dict
        "check": "हस्ताक्षर जाँचें",                                                                     # dict
        "checkHow": "सबूत फ़ाइल पूरी होने पर जलस्मृति ने उसके डिजिटल फ़िंगरप्रिंट और समय दर्ज किए, फिर उस बयान पर ऐसी ECDSA P-256 कुंजी से हस्ताक्षर किए जो कभी AWS KMS से बाहर नहीं जाती। आपका ब्राउज़र सार्वजनिक कुंजी डाउनलोड करता है और Web Crypto API से खुद हस्ताक्षर की जाँच करता है, इसलिए आपको इस सर्वर की बात पर भरोसा करने की ज़रूरत नहीं है।",  # dict
        "footer": "जलस्मृति जनहित में फ़ैसले लेने में मदद करने वाला साधन है। सैटेलाइट से बनी सीमाएँ अनुमानित हैं, यह ज़मीन का सर्वे नहीं है।",  # dict
        "page": "पृष्ठ {n} / {total}",
        "tierLabel": "पानी की गहरी याद", "indexLabel": _f("100 में से {n}", n=79),                       # dict
        "explain": "यह आँकड़ा चार भारतीय शहरों के आम बसे हुए इलाकों से तुलना करके निकाला गया है। यह इतिहास और ज़मीन की बनावट बताता है; यह बाढ़ का पूर्वानुमान नहीं है।",  # dict
        "validation": "हमारी जाँच में, जिन इलाकों में बाढ़ आने की खबर थी, उनमें से 15% में पानी की कम याद थी, जबकि आम बसे हुए इलाकों में यह आँकड़ा 43% था।",  # dict
        "f": [(_f("1984 से 2020 के बीच ठीक इसी जगह पर {pct}% तस्वीरों में सैटेलाइट को पानी दिखा।", pct=62), "high"),  # dict
              (_f("2 किमी के भीतर पुराने जलाशयों के {ha} हेक्टेयर तल पर अब निर्माण हो चुका है।", ha=21.4), "high"),  # dict
              (_f("{date} को रडार ने 300 मीटर के भीतर असामान्य जमा पानी देखा ({ha} हेक्टेयर)।", date="18 अग 2025", ha=1.3), "high"),  # dict
              (_f("300 मीटर के भीतर जो पानी था, उसमें से {ha} हेक्टेयर 1984 के बाद से गायब हो चुका है।", ha=4.2), "medium"),  # dict
              (_f("300 मीटर के भीतर ज़मीन {m} मीटर तक गहरे कटोरे जैसी है, जहाँ बारिश का पानी जमा हो सकता है।", m=2.1), "medium"),  # dict
              ("इस जगह का कुछ हिस्सा पानी बहने के सबसे नज़दीकी प्राकृतिक रास्ते से 1 मीटर से भी कम ऊँचाई पर है।", "medium"),  # dict
              (_f("सबसे नज़दीकी पुराना जलाशय {m} मीटर दूर है।", m=180), "info")],                                    # dict
        "radarSentence": _f("मानसून की {scenes} रडार तस्वीरों में {n} बार पानी दिखा", n=3, scenes=41),            # dict
        "radarDates": ["5 सितं 2022", "12 अक्टू 2024", "18 अग 2025"],
        "heatLines": ["14 मई 2026 को यहाँ ज़मीन का तापमान 46 °C तक पहुँचा, जो शहर के सबसे गर्म हिस्सों में है।",
                      "300 मीटर के भीतर पेड़ों का आवरण: 6%। गर्मियों में छाया और हवा का आना-जाना ज़रूरी है।"],
        "heatScale": "25 °C से 50 °C",
        "reportSentence": "आस-पास के लोगों ने जून 2026 से 2 बार जमा पानी की खबर दी।",
        "reportItems": ["12 सितं 2026, 350 मीटर दूर: मुख्य सड़क पर एक दिन तक घुटनों तक पानी",
                        "28 जुल 2026, 600 मीटर दूर: बेसमेंट पार्किंग में पानी"],
        "actionsTitle": "इस हफ़्ते, सौदा पक्का करने से पहले",
        "actionItems": ["खरीद रहे हैं या किराये पर ले रहे हैं? ज़मीन का राजस्व रिकॉर्ड माँगें और पूछें कि क्या वह कभी तालाब या झील का तल थी, और स्थानीय मास्टर प्लान में नालों और झीलों के बफ़र ज़ोन देखें।",  # dict
                        "भारी बारिश के अगले दिन जगह देखने जाएँ और दीवारों व गेट पर पानी के निशान देखें।",
                        "दो पड़ोसियों से पूछें कि पिछले मानसून में पानी कहाँ तक आया था।",
                        "यहाँ रहते हैं? मानसून से पहले नालियाँ साफ़ रखें और पास की झील के लिए बने समूह से जुड़ें या नया समूह शुरू करें।"],  # dict
        "qs": ["क्या यह ज़मीन कभी तालाब, झील का तल या नाला थी? क्या मैं राजस्व रिकॉर्ड देख सकता हूँ?",
                      "क्या किसी मानसून में पानी इमारत, बेसमेंट या पार्किंग में घुसा? कितना गहरा और कितनी देर के लिए?",
                      "सड़क और प्लॉट का बारिश का पानी कहाँ बहकर जाता है, और उस नाले को कौन साफ़ करता है?",
                      "क्या प्लॉट मास्टर प्लान में किसी झील या नाले के बफ़र ज़ोन में आता है?"],
        "lims": ["पिक्सेल 10 से 30 मीटर के होते हैं।", "रडार ऊँची इमारतों के बीच नहीं देख सकता।",              # dict
                   "पानी की याद इतिहास है, बाढ़ का पूर्वानुमान नहीं।",                                               # dict
                   "सैटेलाइट से बनी सीमाएँ अनुमानित हैं, यह ज़मीन का सर्वे नहीं है।"],                                # dict
        "sources": "1987 से Landsat 4-9 और Sentinel-2, Sentinel-1 रडार, JRC Global Surface Water, Impact Observatory का ज़मीन-आवरण डेटा, ESA WorldCover, Copernicus ऊँचाई डेटा, NASA POWER बारिश डेटा, और OpenStreetMap व GeoNames से नाम।",  # dict
    },
    "kn": {
        "title": "ಬೆಳ್ಳಂದೂರು, ಬೆಂಗಳೂರು", "lat": 12.9352, "lon": 77.6807, "tier": "some", "index": 54,
        "docTitle": "ಜಲಸ್ಮೃತಿ ಸ್ಥಳ ವರದಿ", "signedNote": "ಡಿಜಿಟಲ್ ಸಹಿ: ಕೊನೆಯ ಪುಟದಲ್ಲಿ ಪರಿಶೀಲಿಸಿ",
        "made": "ಸಿದ್ಧಪಡಿಸಿದ ಸಮಯ: 11 ಅಕ್ಟೋ 2026, 09:12 IST",
        "checked": _f("{date} ರಂದು ಪರಿಶೀಲಿಸಲಾಗಿದೆ", date="10 ಅಕ್ಟೋ 2026"),                                  # dict
        "coords": _f("{lat} ಉತ್ತರ, {lon} ಪೂರ್ವ", lat="12.93520", lon="77.68070"),                           # dict
        "memoryTitle": "ಈ ಸ್ಥಳಕ್ಕೆ ಏನು ನೆನಪಿದೆ", "findings": "ದಾಖಲೆಗಳು ಏನು ತೋರಿಸುತ್ತವೆ",                    # dict
        "timelapse": "ವರ್ಷಗಳುದ್ದಕ್ಕೂ ಅದೇ ಜಾಗ", "radar": "ಮಳೆಗಾಲದಲ್ಲಿ ರೇಡಾರ್ ಕಂಡ ನೀರು",                     # dict
        "heat": "ಬೇಸಿಗೆಯ ಬಿಸಿ", "reports": "ಹತ್ತಿರದಲ್ಲಿ ವರದಿಯಾದ ನಿಂತ ನೀರು",
        "actions": "ನೀವು ಏನು ಮಾಡಬಹುದು",                                                                 # dict
        "questions": "ಮಾಲೀಕರನ್ನು ಕೇಳಬೇಕಾದ ಪ್ರಶ್ನೆಗಳು",
        "limits": "ಮಿತಿಗಳ ಬಗ್ಗೆ ಪ್ರಾಮಾಣಿಕತೆ", "verification": "ನೀವೇ ಪರಿಶೀಲಿಸಬಹುದಾದ ಸಾಕ್ಷ್ಯ",                  # dict
        "payload": "ವಿಷಯದ ಡಿಜಿಟಲ್ ಬೆರಳಚ್ಚು", "key": "ಸಹಿ ಕೀಯ ಡಿಜಿಟಲ್ ಬೆರಳಚ್ಚು", "check": "ಸಹಿ ಪರಿಶೀಲಿಸಿ",  # dict
        "checkHow": "ಕಡತ ಪೂರ್ಣಗೊಂಡಾಗ, ಜಲಸ್ಮೃತಿ ಅದರ ಡಿಜಿಟಲ್ ಬೆರಳಚ್ಚುಗಳನ್ನು ಮತ್ತು ಸಮಯವನ್ನು ಬರೆದಿಟ್ಟು, ಆ ಹೇಳಿಕೆಗೆ AWS KMS ಸೇವೆಯಿಂದ ಎಂದಿಗೂ ಹೊರಹೋಗದ ECDSA P-256 ಕೀ ಬಳಸಿ ಸಹಿ ಮಾಡಿತು. ನಿಮ್ಮ ಬ್ರೌಸರ್ ಸಾರ್ವಜನಿಕ ಕೀಯನ್ನು ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ, Web Crypto API ಬಳಸಿ ಸಹಿಯನ್ನು ತಾನೇ ಪರಿಶೀಲಿಸುತ್ತದೆ; ಹೀಗಾಗಿ ಈ ಸರ್ವರ್ ಹೇಳುವುದನ್ನು ನೀವು ಕಣ್ಣುಮುಚ್ಚಿ ನಂಬಬೇಕಾಗಿಲ್ಲ.",  # dict
        "footer": "ಜಲಸ್ಮೃತಿ ಸಾರ್ವಜನಿಕ ಹಿತಕ್ಕಾಗಿ ರೂಪಿಸಿದ, ನಿರ್ಧಾರ ಕೈಗೊಳ್ಳಲು ನೆರವಾಗುವ ಸಾಧನ. ಉಪಗ್ರಹದಿಂದ ಪಡೆದ ಗಡಿರೇಖೆಗಳು ಅಂದಾಜು ಮಾತ್ರ; ಅವು ಭೂಮಾಪನ ಅಲ್ಲ.",  # dict
        "page": "ಪುಟ {n} / {total}",
        "tierLabel": "ನೀರಿನ ನೆನಪು ಸ್ವಲ್ಪ ಇದೆ", "indexLabel": _f("100ರಲ್ಲಿ {n}", n=54),                     # dict
        "explain": "ನಾಲ್ಕು ಭಾರತೀಯ ನಗರಗಳಲ್ಲಿ ಕಟ್ಟಡಗಳಿರುವ ಸಾಮಾನ್ಯ ಪ್ರದೇಶಗಳೊಂದಿಗೆ ಹೋಲಿಸಲಾಗಿದೆ. ಇದು ಇತಿಹಾಸ ಮತ್ತು ನೆಲದ ಏರಿಳಿತವನ್ನು ವಿವರಿಸುತ್ತದೆ; ಇದು ಪ್ರವಾಹದ ಮುನ್ಸೂಚನೆ ಅಲ್ಲ.",  # dict
        "validation": "ನಮ್ಮ ಪರೀಕ್ಷೆಯಲ್ಲಿ, ಪ್ರವಾಹ ವರದಿಯಾದ ಬಡಾವಣೆಗಳ ಪೈಕಿ 15% ಬಡಾವಣೆಗಳಲ್ಲಿ ನೀರಿನ ನೆನಪು ಕಡಿಮೆ ಇತ್ತು; ಕಟ್ಟಡಗಳಿರುವ ಸಾಮಾನ್ಯ ಪ್ರದೇಶಗಳಲ್ಲಿ ಈ ಪ್ರಮಾಣ 43%.",  # dict
        "f": [(_f("1984 ಮತ್ತು 2020ರ ನಡುವೆ, {pct}% ಉಪಗ್ರಹ ಚಿತ್ರಗಳಲ್ಲಿ ಇದೇ ಜಾಗದಲ್ಲಿ ನೀರು ಕಂಡಿದೆ.", pct=31), "medium"),  # dict
              (_f("2 ಕಿ.ಮೀ. ಒಳಗೆ, ಹಳೆಯ ಜಲಮೂಲಗಳ ಅಂಗಳದ {ha} ಹೆಕ್ಟೇರ್ ಈಗ ಕಟ್ಟಡಗಳ ಪಾಲಾಗಿದೆ.", ha=21.4), "high"),  # dict
              (_f("300 ಮೀ. ಒಳಗಿನ ನೆಲ {m} ಮೀ. ವರೆಗೆ ಆಳವಿರುವ ಬಟ್ಟಲಿನಂತಿದೆ; ಅಲ್ಲಿ ಮಳೆನೀರು ನಿಲ್ಲಬಹುದು.", m=2.1), "medium"),  # dict
              ("ಈ ಸ್ಥಳದ ಒಂದು ಭಾಗ ಹತ್ತಿರದ ನೈಸರ್ಗಿಕ ನೀರು ಹರಿವಿನ ಮಾರ್ಗದಿಂದ 1 ಮೀ. ಗಿಂತ ಕಡಿಮೆ ಎತ್ತರದಲ್ಲಿದೆ.", "medium"),  # dict
              (_f("{date} ರಂದು 300 ಮೀ. ಒಳಗೆ ಅಸಾಮಾನ್ಯವಾಗಿ ನಿಂತ ನೀರನ್ನು ರೇಡಾರ್ ಕಂಡಿದೆ ({ha} ಹೆಕ್ಟೇರ್).", date="18 ಆಗ 2025", ha=1.3), "high"),  # dict
              (_f("ದಾಖಲೆಯಲ್ಲಿರುವ ಹತ್ತಿರದ ಜಲಮೂಲ {m} ಮೀ. ದೂರದಲ್ಲಿದೆ.", m=180), "info")],                    # dict
        "radarSentence": _f("{scenes} ಮಳೆಗಾಲದ ರೇಡಾರ್ ಚಿತ್ರಗಳಲ್ಲಿ {n} ಬಾರಿ ನೀರು ಕಂಡಿದೆ", n=3, scenes=41),  # dict
        "radarDates": ["5 ಸೆಪ್ಟೆಂ 2022", "12 ಅಕ್ಟೋ 2024", "18 ಆಗ 2025"],
        "heatLines": ["14 ಮೇ 2026 ರಂದು ಇಲ್ಲಿನ ನೆಲದ ತಾಪಮಾನ 46 °C ತಲುಪಿತ್ತು.", "300 ಮೀ. ಒಳಗೆ ಮರಗಳ ಹೊದಿಕೆ: 6%."],
        "heatScale": "25 °C ರಿಂದ 50 °C",
        "reportSentence": "ಜೂನ್ 2026ರಿಂದ ಹತ್ತಿರದ ಜನರು 2 ಬಾರಿ ನಿಂತ ನೀರಿನ ಬಗ್ಗೆ ವರದಿ ಮಾಡಿದ್ದಾರೆ.",
        "reportItems": ["12 ಸೆಪ್ಟೆಂ 2026, 350 ಮೀ. ದೂರ: ಮುಖ್ಯ ರಸ್ತೆಯಲ್ಲಿ ಮೊಣಕಾಲುದ್ದ ನೀರು",
                        "28 ಜುಲೈ 2026, 600 ಮೀ. ದೂರ: ನೆಲಮಾಳಿಗೆಯ ವಾಹನ ನಿಲುಗಡೆಯಲ್ಲಿ ನೀರು"],
        "actionsTitle": "ಈ ವಾರ, ಒಪ್ಪಂದಕ್ಕೆ ಸಹಿ ಹಾಕುವ ಮೊದಲು",
        "actionItems": ["ಇಲ್ಲಿ ಆಸ್ತಿ ಖರೀದಿಸುತ್ತಿದ್ದೀರಾ ಅಥವಾ ಬಾಡಿಗೆಗೆ ಬರುತ್ತಿದ್ದೀರಾ? ಆ ಜಮೀನಿನ ಕಂದಾಯ ದಾಖಲೆಯನ್ನು ಕೇಳಿ, ಅದು ಎಂದಾದರೂ ಕೆರೆ ಅಥವಾ ಕೆರೆಯಂಗಳವಾಗಿತ್ತೇ ಎಂದು ವಿಚಾರಿಸಿ, ಮತ್ತು ಸ್ಥಳೀಯ ಮಹಾಯೋಜನೆಯಲ್ಲಿ (ಮಾಸ್ಟರ್ ಪ್ಲಾನ್) ರಾಜಕಾಲುವೆ ಮತ್ತು ಕೆರೆಯ ಬಫರ್ ವಲಯಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.",  # dict
                        "ಇಲ್ಲೇ ವಾಸಿಸುತ್ತಿದ್ದೀರಾ? ಮಳೆಗಾಲಕ್ಕೆ ಮುನ್ನ ಚರಂಡಿಗಳನ್ನು ಸ್ವಚ್ಛವಾಗಿಡಿ, ಮತ್ತು ಹತ್ತಿರದ ಕೆರೆಗಾಗಿ ಇರುವ ಗುಂಪಿಗೆ ಸೇರಿ ಅಥವಾ ಹೊಸ ಗುಂಪು ಆರಂಭಿಸಿ.",  # dict
                        "ಹತ್ತಿರದ ಜಲಮೂಲ ತೆರೆಯಿರಿ"],                                                    # dict
        "qs": ["ಈ ಜಮೀನು ಎಂದಾದರೂ ಕೆರೆ ಅಥವಾ ಕೆರೆಯಂಗಳವಾಗಿತ್ತೇ?", "ಈ ಜಮೀನಿನ ಕಂದಾಯ ದಾಖಲೆಯನ್ನು ನೋಡಬಹುದೇ?",
                      "ಸ್ಥಳೀಯ ಮಹಾಯೋಜನೆಯಲ್ಲಿ ಈ ಜಾಗ ರಾಜಕಾಲುವೆ ಅಥವಾ ಕೆರೆಯ ಬಫರ್ ವಲಯದಲ್ಲಿದೆಯೇ?"],
        "lims": ["ಪ್ರತಿ ಪಿಕ್ಸೆಲ್ 10 ರಿಂದ 30 ಮೀ. ಗಾತ್ರದ್ದು.", "ಎತ್ತರದ ಕಟ್ಟಡಗಳ ನಡುವಿನ ಜಾಗವನ್ನು ರೇಡಾರ್ ನೋಡಲಾರದು.",  # dict
                   "ನೀರಿನ ನೆನಪು ಎಂದರೆ ಇತಿಹಾಸ, ಪ್ರವಾಹದ ಮುನ್ಸೂಚನೆ ಅಲ್ಲ.",                                           # dict
                   "ಉಪಗ್ರಹದಿಂದ ಪಡೆದ ಗಡಿರೇಖೆಗಳು ಅಂದಾಜು ಮಾತ್ರ; ಅವು ಭೂಮಾಪನ ಅಲ್ಲ."],                               # dict
        "sources": "1987ರಿಂದ Landsat 4-9 ಮತ್ತು Sentinel-2, Sentinel-1 ರೇಡಾರ್, JRC Global Surface Water, Impact Observatory ಭೂ ಹೊದಿಕೆ, ESA WorldCover, Copernicus ಎತ್ತರ ದತ್ತಾಂಶ, NASA POWER ಮಳೆ ದತ್ತಾಂಶ, OpenStreetMap ಮತ್ತು GeoNames ಹೆಸರುಗಳು.",  # dict
    },
    "ta": {
        "title": "பெள்ளந்தூர், பெங்களூரு", "lat": 12.9352, "lon": 77.6807, "tier": "little", "index": 22,
        "docTitle": "JalSmriti இட அறிக்கை", "signedNote": "டிஜிட்டல் கையொப்பம்: கடைசிப் பக்கத்தில் சரிபாருங்கள்",
        "made": "தயாரித்தது: 11 அக். 2026, 09:12 IST",
        "checked": _f("{date} அன்று சரிபார்க்கப்பட்டது", date="10 அக். 2026"),                              # dict
        "coords": _f("{lat} வடக்கு, {lon} கிழக்கு", lat="12.93520", lon="77.68070"),                        # dict
        "memoryTitle": "இந்த இடம் நினைவில் வைத்திருப்பது", "findings": "பதிவுகள் காட்டுவது",                 # dict
        "timelapse": "ஆண்டுவாரியாக இதே இடம்", "radar": "பருவமழைக் கால ரேடார் கண்டறிதல்கள்",                  # dict
        "heat": "கோடை வெப்பம்", "reports": "அருகில் தெரிவிக்கப்பட்ட தேங்கிய நீர்",
        "actions": "நீங்கள் செய்யக்கூடியவை",                                                           # dict
        "questions": "உரிமையாளரிடம் கேட்க வேண்டியவை",
        "limits": "வரம்புகளை மறைப்பதில்லை", "verification": "நீங்களே சரிபார்க்கக்கூடிய ஆதாரம்",            # dict
        "payload": "உள்ளடக்கத்தின் டிஜிட்டல் கைரேகை", "key": "கையொப்பச் சாவியின் டிஜிட்டல் கைரேகை",      # dict
        "check": "கையொப்பத்தைச் சரிபார்க்க",                                                            # dict
        "checkHow": "ஆவணத் தொகுப்பு முடிந்ததும், JalSmriti அதன் டிஜிட்டல் கைரேகைகளையும் நேரத்தையும் ஓர் அறிக்கையாக எழுதி, AWS KMS-ஐ விட்டு ஒருபோதும் வெளியேறாத ECDSA P-256 சாவியால் அந்த அறிக்கையில் கையொப்பமிட்டது. உங்கள் உலாவி பொதுச் சாவியைப் பதிவிறக்கி, Web Crypto API மூலம் கையொப்பத்தைத் தானே சரிபார்க்கிறது; எனவே இந்தச் சர்வர் சொல்வதை நீங்கள் அப்படியே நம்ப வேண்டியதில்லை.",  # dict
        "footer": "JalSmriti பொதுநலன் சார்ந்த, முடிவெடுக்க உதவும் ஒரு கருவி. செயற்கைக்கோள் மூலம் வரையப்பட்ட எல்லைகள் தோராயமானவை; அவை நில அளவைப் பதிவு அல்ல.",  # dict
        "page": "பக்கம் {n} / {total}",
        "tierLabel": "குறைந்த நீர் நினைவு", "indexLabel": _f("100-க்கு {n}", n=22),                         # dict
        "explain": "நான்கு இந்திய நகரங்களின் சாதாரண கட்டடப் பகுதிகளுடன் ஒப்பிடப்பட்டது. இது வரலாற்றையும் நில அமைப்பையும் விவரிக்கிறது; வெள்ள முன்னறிவிப்பு அல்ல.",  # dict
        "validation": "எங்கள் சோதனையில், வெள்ளம் பாதித்ததாகப் பதிவான பகுதிகளில் 15% குறைந்த நீர் நினைவு கொண்டிருந்தன; சாதாரண கட்டடப் பகுதிகளில் இந்த அளவு 43%.",  # dict
        "f": [(_f("1984 முதல், 300 மீ சுற்றளவில் இருந்த நீர்ப்பரப்பில் {ha} ஹெக்டேர் மறைந்துவிட்டது.", ha=0.6), "low"),  # dict
              (_f("பதிவில் உள்ள மிக அருகிலான நீர்நிலை {m} மீ தொலைவில் உள்ளது.", m=640), "info"),                     # dict
              ("37 ஆண்டுகால செயற்கைக்கோள் பதிவுகளில், இங்கு வலுவான நீர் வரலாறு எதுவும் காணப்படவில்லை.", "info")],      # dict
        "radarSentence": _f("{n} பருவமழைக் கால ரேடார் பதிவுகளில், 300 மீ சுற்றளவில் அசாதாரணமாகத் தேங்கிய நீர் எதுவும் தென்படவில்லை. உயரமான கட்டடங்களுக்கு இடையே ரேடாரால் பார்க்க முடியாது; எனவே இங்கு ஒருபோதும் வெள்ளம் வராது என்று இதற்குப் பொருள் இல்லை.", n=41),  # dict
        "radarDates": [],
        "heatLines": ["14 மே 2026 அன்று இங்கு நிலத்தின் வெப்பநிலை 46 °C-ஐ எட்டியது.", "300 மீ சுற்றளவில் மரங்களின் பரப்பு: 6%."],
        "heatScale": "25 °C முதல் 50 °C வரை",
        "reportSentence": "", "reportItems": [],
        "actionsTitle": "இந்த வாரம், ஒப்பந்தத்தில் கையெழுத்திடும் முன்",
        "actionItems": ["இங்கு வாங்கவோ வாடகைக்கு எடுக்கவோ போகிறீர்களா? நிலத்தின் வருவாய்த் துறைப் பதிவுகளைக் கேட்டு, அது எப்போதாவது ஏரி அல்லது குளப் படுகையாக இருந்ததா என்று விசாரியுங்கள்; உள்ளூர் முழுமைத் திட்டத்தில் (மாஸ்டர் பிளான்) வடிகால்கள், ஏரிகளைச் சுற்றியுள்ள பாதுகாப்பு இடைவெளிப் பகுதிகளையும் சரிபாருங்கள்.",  # dict
                        "இங்கு வசிக்கிறீர்களா? பருவமழைக்கு முன் வடிகால்களில் அடைப்பு இல்லாமல் பார்த்துக்கொள்ளுங்கள்; அருகிலுள்ள ஏரிக்கான குழுவில் சேருங்கள், அல்லது புதிதாக ஒரு குழுவைத் தொடங்குங்கள்.",  # dict
                        "அருகிலுள்ள நீர்நிலையைத் திறக்க"],                                             # dict
        "qs": ["இந்த நிலம் எப்போதாவது ஏரி அல்லது குளப் படுகையாக இருந்ததா?",
                      "நிலத்தின் வருவாய்த் துறைப் பதிவுகளைப் பார்க்கலாமா?",
                      "உள்ளூர் முழுமைத் திட்டத்தில் இந்த இடம் வடிகால் அல்லது ஏரியின் பாதுகாப்பு இடைவெளிப் பகுதியில் உள்ளதா?"],
        "lims": ["ஒவ்வொரு பிக்சலும் 10 முதல் 30 மீ அளவு.", "உயரமான கட்டடங்களுக்கு இடையே ரேடாரால் பார்க்க முடியாது.",  # dict
                   "நீர் நினைவு என்பது வரலாறு; வெள்ள முன்னறிவிப்பு அல்ல.",                                         # dict
                   "செயற்கைக்கோள் மூலம் வரையப்பட்ட எல்லைகள் தோராயமானவை; அவை நில அளவைப் பதிவு அல்ல."],               # dict
        "sources": "1987 முதல் Landsat 4-9 மற்றும் Sentinel-2, Sentinel-1 ரேடார், JRC Global Surface Water, Impact Observatory நில மேற்பரப்புத் தரவு, ESA WorldCover, Copernicus உயரத் தரவு, NASA POWER மழைத் தரவு, OpenStreetMap மற்றும் GeoNames பெயர்கள்.",  # dict
    },
    "te": {
        "title": "బెళ్ళందూర్, బెంగళూరు", "lat": 12.9352, "lon": 77.6807, "tier": "strong", "index": 83,
        "docTitle": "జలస్మృతి ప్రాంత నివేదిక", "signedNote": "డిజిటల్ సంతకం: చివరి పేజీలో తనిఖీ చేయండి",
        "made": "సిద్ధం చేసిన సమయం: 11 అక్టో 2026, 09:12 IST",
        "checked": _f("తనిఖీ తేదీ: {date}", date="10 అక్టో 2026"),                                          # dict
        "coords": _f("{lat} ఉత్తరం, {lon} తూర్పు", lat="12.93520", lon="77.68070"),                          # dict
        "memoryTitle": "ఈ ప్రాంతం ఏం గుర్తుంచుకుంది", "findings": "రికార్డులు ఏం చెబుతున్నాయి",               # dict
        "timelapse": "ఏళ్లుగా అదే చోటు", "radar": "వర్షాకాలంలో రాడార్‌కు కనిపించిన నీరు",                    # dict
        "heat": "వేసవి వేడి", "reports": "దగ్గర్లో నమోదైన నిలిచిన నీరు",
        "actions": "మీరు ఏం చేయవచ్చు",                                                                  # dict
        "questions": "యజమానిని అడగాల్సిన ప్రశ్నలు",
        "limits": "పరిమితులపై నిజాయితీ", "verification": "మీరే సరిచూసుకోగల ఆధారాలు",                       # dict
        "payload": "కంటెంట్ వేలిముద్ర", "key": "సంతకం కీ వేలిముద్ర", "check": "సంతకాన్ని ధ్రువీకరించండి",     # dict
        "checkHow": "ఆధారాల పత్రం పూర్తయినప్పుడు, జలస్మృతి దాని వేలిముద్రలను, సమయాన్ని నమోదు చేసి, ఆ ప్రకటనపై AWS KMS నుంచి ఎప్పుడూ బయటకు రాని ECDSA P-256 కీతో సంతకం చేసింది. మీ బ్రౌజర్ పబ్లిక్ కీని డౌన్‌లోడ్ చేసుకుని, Web Crypto API ద్వారా సంతకాన్ని స్వయంగా తనిఖీ చేస్తుంది. కాబట్టి ఈ సర్వర్ మాట మీద మీరు ఆధారపడాల్సిన అవసరం లేదు.",  # dict
        "footer": "జలస్మృతి ప్రజాప్రయోజనం కోసం నిర్ణయాలకు తోడ్పడే సాధనం. ఉపగ్రహ సరిహద్దులు సుమారువి మాత్రమే; అవి భూ సర్వే కాదు.",  # dict
        "page": "పేజీ {n} / {total}",
        "tierLabel": "బలమైన నీటి జ్ఞాపకం", "indexLabel": _f("100కి {n}", n=83),                            # dict
        "explain": "నాలుగు భారతీయ నగరాల్లోని, కట్టడాలున్న సాధారణ ప్రాంతాలతో పోల్చి చూశాం. ఇది చరిత్రను, నేల ఎత్తుపల్లాలను వివరిస్తుంది; ఇది వరద ముందస్తు అంచనా కాదు.",  # dict
        "validation": "మా పరీక్షలో, వరద వచ్చినట్లు నమోదైన ప్రాంతాల్లో 15% ప్రాంతాలకు తక్కువ నీటి జ్ఞాపకం ఉంది; కట్టడాలున్న సాధారణ ప్రాంతాల్లో ఇది 43%.",  # dict
        "f": [(_f("1984 నుంచి 2020 మధ్య జరిగిన ఉపగ్రహ పరిశీలనల్లో {pct}% సార్లు సరిగ్గా ఈ చోటే నీరు కనిపించింది.", pct=62), "high"),  # dict
              (_f("2 కి.మీ. పరిధిలో, పాత నీటి వనరుల గర్భాల్లో {ha} హెక్టార్ల మేర ఇప్పుడు కట్టడాలు ఉన్నాయి.", ha=21.4), "high"),  # dict
              (_f("300 మీ. పరిధిలోని నేల {m} మీ. లోతు వరకు గిన్నెలా ఉంది; అక్కడ వాన నీరు నిలవవచ్చు.", m=2.1), "medium"),  # dict
              ("ఈ ప్రాంతంలో కొంత భాగం, దగ్గర్లోని సహజ నీటి ప్రవాహ మార్గం కంటే 1 మీ. కన్నా తక్కువ ఎత్తులో ఉంది.", "medium"),  # dict
              (_f("{date}న 300 మీ. పరిధిలో అసాధారణంగా నిలిచిన నీటిని రాడార్ గుర్తించింది ({ha} హెక్టార్లు).", date="18 ఆగ 2025", ha=1.3), "high")],  # dict
        "radarSentence": _f("{scenes} వర్షాకాల రాడార్ పరిశీలనల్లో {n} సార్లు నీరు కనిపించింది", n=3, scenes=41),  # dict
        "radarDates": ["5 సెప్టెం 2022", "12 అక్టో 2024", "18 ఆగ 2025"],
        "heatLines": ["14 మే 2026న ఇక్కడ నేల ఉష్ణోగ్రత 46 °Cకి చేరింది.", "300 మీ. పరిధిలో చెట్ల విస్తీర్ణం: 6%."],
        "heatScale": "25 °C నుంచి 50 °C",
        "reportSentence": "జూన్ 2026 నుంచి దగ్గర్లోని వారు 2 సార్లు నిలిచిన నీటి గురించి తెలిపారు.",
        "reportItems": ["12 సెప్టెం 2026, 350 మీ. దూరంలో: ప్రధాన రహదారిపై మోకాలి లోతు నీరు"],
        "actionsTitle": "ఈ వారం, ఒప్పందంపై సంతకం చేసే ముందు",
        "actionItems": ["కొంటున్నారా, అద్దెకు తీసుకుంటున్నారా? ఆ భూమి రెవెన్యూ రికార్డులను, అది ఎప్పుడైనా చెరువు లేదా సరస్సు గర్భం (శిఖం) అయిందా అన్న వివరాన్ని అడగండి; స్థానిక మాస్టర్ ప్లాన్‌లో నాలాలు, చెరువుల బఫర్ జోన్‌లను తనిఖీ చేయండి.",  # dict
                        "ఇక్కడ నివసిస్తున్నారా? వర్షాకాలానికి ముందే కాలువల్లో అడ్డంకులు లేకుండా చూసుకోండి; దగ్గర్లోని చెరువు కోసం పనిచేసే బృందంలో చేరండి, లేదా కొత్త బృందాన్ని ప్రారంభించండి.",  # dict
                        "దగ్గర్లోని నీటి వనరును తెరవండి"],                                            # dict
        "qs": ["ఈ భూమి ఎప్పుడైనా చెరువు లేదా సరస్సు గర్భం (శిఖం) అయిందా?", "ఆ భూమి రెవెన్యూ రికార్డులను చూడవచ్చా?"],
        "lims": ["ఎత్తైన భవనాల మధ్య రాడార్ చూడలేదు.", "నీటి జ్ఞాపకం అంటే చరిత్ర, వరద ముందస్తు అంచనా కాదు.",  # dict
                   "ఉపగ్రహ సరిహద్దులు సుమారువి మాత్రమే; అవి భూ సర్వే కాదు."],                                  # dict
        "sources": "1987 నుంచి Landsat 4-9, Sentinel-2; Sentinel-1 రాడార్; JRC Global Surface Water; Impact Observatory భూ వినియోగ సమాచారం; ESA WorldCover; Copernicus ఎత్తు సమాచారం; NASA POWER వర్షపాతం; OpenStreetMap, GeoNames పేర్లు.",  # dict
    },
    "ml": {
        "title": "ബെല്ലന്തൂർ, ബെംഗളൂരു", "lat": 12.9352, "lon": 77.6807, "tier": "some", "index": 47,
        "docTitle": "ജലസ്മൃതി സ്ഥല റിപ്പോർട്ട്", "signedNote": "ഡിജിറ്റൽ ഒപ്പോടെ: അവസാന പേജിൽ പരിശോധിക്കുക",
        "made": "തയ്യാറാക്കിയത്: 11 ഒക്ടോ 2026, 09:12 IST",
        "checked": _f("{date}-ന് പരിശോധിച്ചത്", date="10 ഒക്ടോ 2026"),                                       # dict
        "coords": _f("{lat} N, {lon} E", lat="12.93520", lon="77.68070"),                                    # dict
        "memoryTitle": "ഈ സ്ഥലം ഓർക്കുന്നത്", "findings": "രേഖകൾ കാണിക്കുന്നത്",                              # dict
        "timelapse": "ഇതേ സ്ഥലം, വർഷങ്ങളിലൂടെ", "radar": "മൺസൂൺ റഡാർ കണ്ടെത്തലുകൾ",                         # dict
        "heat": "വേനൽച്ചൂട്", "reports": "സമീപത്ത് റിപ്പോർട്ട് ചെയ്ത വെള്ളക്കെട്ട്",
        "actions": "നിങ്ങൾക്ക് ചെയ്യാവുന്നത്",                                                         # dict
        "questions": "ഉടമയോട് ചോദിക്കേണ്ടവ",
        "limits": "പരിമിതികൾ മറച്ചുവയ്ക്കാതെ", "verification": "നിങ്ങൾക്ക് സ്വയം പരിശോധിക്കാവുന്ന തെളിവുകൾ",  # dict
        "payload": "ഉള്ളടക്കത്തിന്റെ വിരലടയാളം", "key": "ഒപ്പിടൽ കീയുടെ വിരലടയാളം", "check": "ഒപ്പ് പരിശോധിക്കുക",  # dict
        "checkHow": "തെളിവ് ഫയൽ പൂർത്തിയായപ്പോൾ ജലസ്മൃതി അതിന്റെ വിരലടയാളങ്ങളും സമയവും രേഖപ്പെടുത്തി, ആ പ്രസ്താവന AWS KMS-ൽ നിന്ന് ഒരിക്കലും പുറത്തുപോകാത്ത ഒരു ECDSA P-256 കീ ഉപയോഗിച്ച് ഒപ്പിട്ടു. നിങ്ങളുടെ ബ്രൗസർ പബ്ലിക് കീ ഡൗൺലോഡ് ചെയ്ത്, Web Crypto API ഉപയോഗിച്ച് സ്വയം ഒപ്പ് പരിശോധിക്കുന്നു; അതിനാൽ ഈ സെർവർ പറയുന്നത് മാത്രം നിങ്ങൾ വിശ്വസിക്കേണ്ടതില്ല.",  # dict
        "footer": "ജലസ്മൃതി, തീരുമാനങ്ങളെടുക്കാൻ സഹായിക്കുന്ന ഒരു പൊതുതാൽപര്യ സംവിധാനമാണ്. ഉപഗ്രഹ ചിത്രങ്ങളിൽ നിന്നുള്ള അതിർത്തികൾ ഏകദേശം മാത്രമാണ്; അവ ഭൂസർവേ അല്ല.",  # dict
        "page": "പേജ് {n} / {total}",
        "tierLabel": "വെള്ളത്തിന്റെ ഓർമ മിതം", "indexLabel": _f("100-ൽ {n}", n=47),                           # dict
        "explain": "നാല് ഇന്ത്യൻ നഗരങ്ങളിലെ സാധാരണ നിർമിത പ്രദേശങ്ങളുമായി താരതമ്യം ചെയ്തുള്ളതാണ്. ഇത് ചരിത്രവും ഭൂപ്രകൃതിയും വിവരിക്കുന്നു; വെള്ളപ്പൊക്ക പ്രവചനമല്ല.",  # dict
        "validation": "ഞങ്ങളുടെ പരിശോധനയിൽ, വെള്ളപ്പൊക്കം റിപ്പോർട്ട് ചെയ്ത പ്രദേശങ്ങളിൽ 15%-ൽ വെള്ളത്തിന്റെ ഓർമ കുറവായിരുന്നു; സാധാരണ നിർമിത പ്രദേശങ്ങളിൽ ഇത് 43% ആയിരുന്നു.",  # dict
        "f": [(_f("2 കി.മീ. ചുറ്റളവിൽ, പഴയ ജലാശയഭൂമിയിൽ {ha} ഹെക്ടറിൽ ഇപ്പോൾ നിർമാണം വന്നിരിക്കുന്നു.", ha=8.7), "high"),  # dict
              (_f("300 മീ. ചുറ്റളവിലെ ഭൂമി {m} മീ. വരെ ആഴമുള്ള ഒരു പാത്രം പോലെ കുഴിഞ്ഞതാണ്; ഇവിടെ മഴവെള്ളം കെട്ടിനിൽക്കാം.", m=1.4), "medium"),  # dict
              ("ഈ സ്ഥലത്തിന്റെ ഒരു ഭാഗം ഏറ്റവും അടുത്തുള്ള സ്വാഭാവിക നീർച്ചാലിൽ നിന്ന് 1 മീ. പോലും ഉയരത്തിലല്ല.", "medium"),  # dict
              (_f("രേഖകളിലുള്ള ഏറ്റവും അടുത്ത ജലാശയം {m} മീ. അകലെയാണ്.", m=320), "info")],                     # dict
        "radarSentence": _f("{scenes} മൺസൂൺ റഡാർ നിരീക്ഷണങ്ങളിൽ {n} കണ്ടെത്തലുകൾ", n=1, scenes=41),           # dict
        "radarDates": ["12 ഒക്ടോ 2024"],
        "heatLines": ["2026 മേയ് 14-ന് ഇവിടെ നിലത്തെ താപനില 46 °C വരെ എത്തി.", "300 മീ. ചുറ്റളവിൽ മരങ്ങളുടെ ആവരണം: 6%."],
        "heatScale": "25 °C മുതൽ 50 °C വരെ",
        "reportSentence": "2026 ജൂൺ മുതൽ സമീപവാസികൾ 2 തവണ വെള്ളക്കെട്ട് റിപ്പോർട്ട് ചെയ്തു.",
        "reportItems": ["12 സെപ്റ്റം 2026, 350 മീ. അകലെ: പ്രധാന റോഡിൽ മുട്ടോളം വെള്ളം"],
        "actionsTitle": "ഈ ആഴ്ച, കരാർ ഒപ്പിടുന്നതിനു മുമ്പ്",
        "actionItems": ["വാങ്ങാനോ വാടകയ്ക്കെടുക്കാനോ പോകുകയാണോ? ഭൂമിയുടെ റവന്യൂ രേഖകൾ ആവശ്യപ്പെടുക; അത് എപ്പോഴെങ്കിലും കുളമോ തടാകമോ ആയിരുന്നോ എന്നും ചോദിക്കുക. പ്രാദേശിക മാസ്റ്റർ പ്ലാനിലെ ഓടകളുടെയും തടാകങ്ങളുടെയും ബഫർ സോണുകളും പരിശോധിക്കുക.",  # dict
                        "ഇവിടെ താമസിക്കുന്നുണ്ടോ? മൺസൂണിനു മുമ്പ് ഓടകൾ വൃത്തിയാക്കി സൂക്ഷിക്കുക; ഏറ്റവും അടുത്തുള്ള തടാകത്തിനായുള്ള കൂട്ടായ്മയിൽ ചേരുകയോ പുതിയൊരെണ്ണം തുടങ്ങുകയോ ചെയ്യുക.",  # dict
                        "ഏറ്റവും അടുത്തുള്ള ജലാശയം തുറക്കുക"],                                         # dict
        "qs": ["ഈ ഭൂമി എപ്പോഴെങ്കിലും കുളമോ തടാകമോ ആയിരുന്നോ?", "ഭൂമിയുടെ റവന്യൂ രേഖകൾ കാണാമോ?"],
        "lims": ["ഓരോ പിക്സലും 10 മുതൽ 30 മീ. വരെ വലുപ്പമുള്ളതാണ്.", "ഉയരമുള്ള കെട്ടിടങ്ങൾക്കിടയിൽ റഡാറിന് കാണാനാവില്ല.",  # dict
                   "വെള്ളത്തിന്റെ ഓർമ ചരിത്രമാണ്, വെള്ളപ്പൊക്ക പ്രവചനമല്ല."],                                         # dict
        "sources": "1987 മുതലുള്ള Landsat 4-9, Sentinel-2 ചിത്രങ്ങൾ, Sentinel-1 റഡാർ, JRC Global Surface Water, Impact Observatory ഭൂ ആവരണ ഡാറ്റ, ESA WorldCover, Copernicus ഉയര ഡാറ്റ, NASA POWER മഴക്കണക്കുകൾ, OpenStreetMap, GeoNames എന്നിവയിലെ സ്ഥലനാമങ്ങൾ.",  # dict
    },
    "ne": {
        "title": "बागमती किनार, काठमाडौं", "lat": 27.691, "lon": 85.314, "tier": "unknown", "index": None,
        "docTitle": "जलस्मृति स्थान प्रतिवेदन", "signedNote": "डिजिटल हस्ताक्षरित: अन्तिम पानामा जाँच्नुहोस्",
        "made": "तयार गरिएको: 11 अक्टोबर 2026, 09:27 NPT",
        "checked": _f("{date} मा जाँचिएको", date="10 अक्टोबर 2026"),                                          # dict
        "coords": _f("{lat} उत्तर, {lon} पूर्व", lat="27.69100", lon="85.31400"),                             # dict
        "memoryTitle": "यो ठाउँले के सम्झन्छ", "findings": "अभिलेखहरूले के देखाउँछन्",                        # dict
        "timelapse": "वर्षैपिच्छे उही ठाउँ", "radar": "मनसुनमा राडारले देखेको पानी",                           # dict
        "heat": "गर्मी", "reports": "नजिकै जमेको पानीका सूचना",
        "actions": "तपाईं के गर्न सक्नुहुन्छ",                                                          # dict
        "questions": "जग्गाधनीलाई सोध्नुपर्ने प्रश्न",
        "limits": "सीमाबारे इमानदार", "verification": "तपाईं आफैँले जाँच्न सक्ने प्रमाण",                   # dict
        "payload": "सामग्रीको फिंगरप्रिन्ट", "key": "हस्ताक्षर कुञ्जीको फिंगरप्रिन्ट", "check": "हस्ताक्षर जाँच्नुहोस्",  # dict
        "checkHow": "प्रमाण फाइल तयार भएपछि जलस्मृतिले त्यसका फिंगरप्रिन्ट र समय टिपेर, AWS KMS बाट कहिल्यै बाहिर नजाने ECDSA P-256 कुञ्जीले त्यो विवरणमा हस्ताक्षर गरेको थियो। तपाईंको ब्राउजरले सार्वजनिक कुञ्जी डाउनलोड गरी Web Crypto API मार्फत आफैँ हस्ताक्षर जाँच्छ, त्यसैले तपाईंले यो सर्भरको भनाइमा मात्र भर पर्नुपर्दैन।",  # dict
        "footer": "जलस्मृति सार्वजनिक हितका लागि बनाइएको निर्णय-सहयोगी साधन हो। भू-उपग्रहबाट निकालिएका सीमारेखा अनुमानित हुन्, जग्गा नापी होइनन्।",  # dict
        "page": "पृष्ठ {n} / {total}",
        "tierLabel": "पर्याप्त तथ्यांक छैन", "indexLabel": "",                                             # dict
        "explain": "भारतका चार सहरका सामान्य बस्ती क्षेत्रसँग तुलना गरिएको। यसले इतिहास र भू-बनोट बताउँछ, यो बाढीको पूर्वानुमान होइन।",  # dict
        "validation": "हाम्रो परीक्षणमा, बाढी आएको भनी रिपोर्ट गरिएका टोलमध्ये 15% मा पानीको थोरै सम्झना थियो, जबकि सामान्य बस्ती क्षेत्रमध्ये 43% मा त्यस्तो थियो।",  # dict
        "f": [(_f("300 मि. भित्र रहेको {ha} हेक्टर पानी 1984 यता हराइसकेको छ।", ha=1.8), "medium"),            # dict
              (_f("नजिकैको पुरानो ताल-पोखरी {m} मि. टाढा छ।", m=90), "info")],                                # dict
        "radarSentence": _f("{scenes} मनसुनी अवलोकनमा {n} पटक पानी देखियो", n=2, scenes=38),                # dict
        "radarDates": ["3 अगस्ट 2023", "21 जुलाई 2025"],
        "heatLines": [], "heatScale": "",
        "reportSentence": "", "reportItems": [],
        "actionsTitle": "यो हप्ता, सम्झौता गर्नुअघि",
        "actionItems": ["किन्दै वा भाडामा लिँदै हुनुहुन्छ? जग्गाको मालपोत अभिलेख माग्नुहोस्, त्यो कुनै बेला पोखरी वा ताल क्षेत्र थियो कि थिएन सोध्नुहोस्, र स्थानीय गुरुयोजनामा नाला तथा ताल वरिपरिको बफर क्षेत्र जाँच्नुहोस्।",  # dict
                        "यहाँ बस्नुहुन्छ? मनसुनअघि नाला सफा राख्नुहोस्, र नजिकैको तालका लागि बनेको समूहमा जोडिनुहोस् वा नयाँ समूह सुरु गर्नुहोस्।"],  # dict
        "qs": [],
        "lims": ["पिक्सेल 10 देखि 30 मि. का हुन्छन्।", "राडारले अग्ला भवनबीच देख्न सक्दैन।",                 # dict
                   "पानीको सम्झना इतिहास हो, बाढीको पूर्वानुमान होइन।"],                                          # dict
        "sources": "1987 देखिका Landsat 4-9 र Sentinel-2, Sentinel-1 राडार, JRC Global Surface Water, Impact Observatory भू-आवरण, ESA WorldCover, Copernicus उचाइ, NASA POWER वर्षा, OpenStreetMap र GeoNames का नामहरू।",  # dict
    },
}

LABEL_KEYS = ["docTitle", "signedNote", "checked", "made", "coords", "memoryTitle", "findings", "timelapse", "radar",
              "heat", "reports", "actions", "questions", "limits", "verification", "payload", "key", "check",
              "checkHow", "footer", "page"]
RAMP = [(0x31, 0x36, 0x95), (0x74, 0xad, 0xd1), (0xfe, 0xe0, 0x90), (0xf4, 0x6d, 0x43), (0xa5, 0x00, 0x26)]


def _frame(i: int, n: int) -> bytes:
    """A small true-colour 'satellite' tile: a lake that shrinks while built-up blocks spread (WebP, as stored)."""
    from PIL import Image, ImageDraw
    rnd = random.Random(7)
    size = 192
    im = Image.blend(Image.new("RGB", (size, size), (104, 122, 84)), Image.effect_noise((size, size), 60).convert("RGB"), 0.22)
    d = ImageDraw.Draw(im)
    for k in range(10 + 9 * i):
        x, y = rnd.randrange(0, size - 20), rnd.randrange(0, size - 20)
        g = rnd.randrange(150, 205)
        d.rectangle((x, y, x + rnd.randrange(8, 22), y + rnd.randrange(8, 22)), fill=(g, g - 6, g - 14))
    r = 70 - 9 * i
    d.ellipse((96 - r, 96 - 0.7 * r, 96 + r, 96 + 0.7 * r), fill=(34, 64, 104))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=80)
    return buf.getvalue()


def _heat_image() -> bytes:
    from PIL import Image
    small = Image.new("RGB", (24, 24))
    for y in range(24):
        for x in range(24):
            t = min(0.999, max(0.0, 0.35 + 0.025 * x - 0.012 * y + (0.3 if (x - 14) ** 2 + (y - 9) ** 2 < 20 else 0)))
            p = t * (len(RAMP) - 1)
            a, b, f = RAMP[int(p)], RAMP[int(p) + 1], p - int(p)
            small.putpixel((x, y), tuple(round(u + (v - u) * f) for u, v in zip(a, b)))
    buf = io.BytesIO()
    small.resize((240, 240), Image.BICUBIC).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _qr(url: str) -> bytes:
    import segno
    buf = io.BytesIO()
    segno.make(url).save(buf, kind="png", scale=6, border=2)
    return buf.getvalue()


def sample(lang: str) -> dict:
    """A realistic report record, as the place handler would pass it, in the reader's language."""
    s = T[lang]
    url = "https://jalsmriti.example/verify/rpt7k2m9q4xa1"
    years = ["1990", "1996", "2002", "2010", "2018", "2025"]
    return {
        "lang": lang, "reportId": "rpt7k2m9q4xa1", "title": s["title"], "lat": s["lat"], "lon": s["lon"],
        "labels": {k: s[k] for k in LABEL_KEYS},
        "tier": s["tier"], "tierLabel": s["tierLabel"], "indexLabel": s["indexLabel"], "index": s["index"],
        "explain": s["explain"], "validation": s["validation"],
        "findings": [{"text": t, "severity": sev} for t, sev in s["f"]],
        "frames": [{"label": y, "image": _frame(i, len(years))} for i, y in enumerate(years)],
        "radar": {"sentence": s["radarSentence"], "dates": s["radarDates"]},
        "heat": ({"lines": s["heatLines"], "image": _heat_image(), "scaleLabel": s["heatScale"], "lo": 25.0, "hi": 50.0}
                 if s["heatLines"] else None),
        "reports": {"sentence": s["reportSentence"], "items": s["reportItems"]} if s["reportSentence"] else None,
        "actions": {"title": s["actionsTitle"], "items": s["actionItems"]},
        "questions": s["qs"] or None,
        "limits": s["lims"], "sources": s["sources"],
        "payloadSha256": "9f2c4be1d07a5e8836c1f4a2b9e07d6c5a3f1e8d2c7b6a5948372615f0e1d2c3",
        "keyFingerprint": "4e1a9c07b2d85f3e6a0c1b9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f",
        "verifyUrl": url, "qrPng": _qr(url),
    }


def page_count(pdf: bytes) -> int:
    try:
        import pypdf
    except ImportError:
        return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf))
    return len(pypdf.PdfReader(io.BytesIO(pdf)).pages)


@pytest.mark.parametrize("lang", LANGS)
def test_renders_in_every_reader_language(lang):
    out = report_pdf.render(sample(lang))
    assert out.startswith(b"%PDF-") and out.rstrip().endswith(b"%%EOF")
    assert 1 <= page_count(out) <= 3


@pytest.mark.parametrize("lang", ["en", "hi", "kn"])
def test_typical_report_takes_two_pages(lang):
    assert page_count(report_pdf.render(sample(lang))) == 2


def test_short_report_fits_one_page():
    d = sample("en")
    d.update(frames=[], radar=None, heat=None, reports=None, questions=None, findings=d["findings"][:2],
             limits=d["limits"][:2])
    d["actions"]["items"] = d["actions"]["items"][:2]
    assert page_count(report_pdf.render(d)) == 1


def test_long_report_stays_within_three_pages():
    d = sample("ta")
    d["findings"] = sample("en")["findings"] * 2
    d["actions"]["items"] = d["actions"]["items"] * 3
    d["questions"] = d["questions"] * 3
    d["reports"] = {"sentence": T["ta"]["checked"], "items": T["ta"]["qs"]}
    out = report_pdf.render(d)
    assert out.startswith(b"%PDF-") and 2 <= page_count(out) <= 3


def test_missing_parts_and_broken_pictures_do_not_stop_the_report():
    d = sample("hi")
    d["title"] = T["kn"]["title"]                       # a place name in another script than the reader's
    d["frames"][2]["image"] = b"not a picture"
    d["heat"]["image"] = b"\x89PNG broken"
    d["qrPng"] = None
    d.update(tier="unknown", index=None, radar={"sentence": "", "dates": []}, reports=None)
    del d["labels"]["page"], d["labels"]["heat"]
    out = report_pdf.render(d)
    assert out.startswith(b"%PDF-") and 1 <= page_count(out) <= 3
    assert b"NotoSansKannada" in out and b"NotoSansDevanagari" in out

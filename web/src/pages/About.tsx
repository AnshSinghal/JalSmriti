import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../lib/api";
import { useT } from "../lib/i18n";

const SECTIONS: [string, string][] = [
  ["methods", "How the water is read"],
  ["grade", "The lake grade"],
  ["validation", "Water memory, tested"],
  ["our-read", "Our read for renters and buyers"],
  ["this-week", "What to do this week"],
  ["rain", "Rain heads-up"],
  ["heat", "Summer heat"],
  ["standing-water", "Standing water from people"],
  ["lake-causes", "Why a lake is like this"],
  ["evidence", "Evidence and dossiers"],
  ["rules", "Access rules"],
  ["privacy", "Privacy"],
  ["limits", "Limits"],
  ["data", "Data and credits"],
  ["open-source", "Open source and AWS"],
  ["credit", "Who made it"],
];

/** Tier shares from docs/validation-data/place_validation.json (39 flooded localities, 240 random built-up places). */
const TIERS = [
  { tier: "Little water memory", flooded: 6, random: 102 },
  { tier: "Some water memory", flooded: 23, random: 99 },
  { tier: "Strong water memory", flooded: 10, random: 39 },
];
const CITY_AUC: [string, number][] = [["Bengaluru", 0.852], ["Delhi", 0.779], ["Hyderabad", 0.571], ["Chennai", 0.548]];

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return <h2 id={id} className="scroll-mt-24 pt-16 text-[clamp(1.8rem,3.4vw,2.4rem)] first:pt-0">{children}</h2>;
}
function P({ children }: { children: React.ReactNode }) {
  return <p className="mt-4 text-[16.5px] leading-[1.65]">{children}</p>;
}

function TierChart() {
  return (
    <figure className="mt-6">
      <div className="space-y-4">
        {TIERS.map((r) => {
          const f = (100 * r.flooded) / 39, x = (100 * r.random) / 240;
          return (
            <div key={r.tier}>
              <div className="text-[15px] font-semibold">{r.tier}</div>
              <div className="mt-1.5 grid grid-cols-[8.5rem_minmax(0,1fr)_3rem] items-center gap-x-3 gap-y-1 text-[13.5px]">
                <span className="text-ink-2">Flooded localities</span>
                <span className="h-3 rounded-sm bg-paper-3"><span className="block h-full rounded-sm bg-built" style={{ width: `${f}%` }} /></span>
                <span className="num text-right text-[14px]">{Math.round(f)}%</span>
                <span className="text-ink-2">Random built-up</span>
                <span className="h-3 rounded-sm bg-paper-3"><span className="block h-full rounded-sm bg-memory" style={{ width: `${x}%` }} /></span>
                <span className="num text-right text-[14px]">{Math.round(x)}%</span>
              </div>
            </div>
          );
        })}
      </div>
      <figcaption className="muted mt-3 text-[13.5px]">Share of each group in each tier: 39 localities reported flooded against 240 random built-up places in the same four cities.</figcaption>
    </figure>
  );
}

export default function About() {
  const { lang, t } = useT();
  const { hash } = useLocation();
  const { data: pol } = useQuery({ queryKey: ["policies"], queryFn: () => api.get<{ cedar: string; rules: Record<string, string> }>("/v1/policies"), staleTime: Infinity });
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    if (el) window.setTimeout(() => el.scrollIntoView({ block: "start" }), 50);
  }, [hash]);

  return (
    <div lang="en" className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      {lang !== "en" && <p className="mb-6 rounded-md bg-paper-2 px-3 py-2 text-[15px]">{t("common.englishOnly")}</p>}
      <h1 className="max-w-[16ch]">How JalSmriti works</h1>
      <p className="mt-5 max-w-[60ch] text-[1.15rem] leading-relaxed text-ink-2">
        JalSmriti reads the public satellite record of India and Nepal to answer two questions in plain words: what does this place remember
        about water, and what is happening to this lake. Everything below is how those answers are made, how well they hold up, and where they stop.
      </p>

      <div className="mt-12 grid gap-12 lg:grid-cols-[15rem_minmax(0,1fr)] [&>*]:min-w-0">
        <nav aria-label="On this page" className="hidden lg:block">
          <ul className="sticky top-24 space-y-2 border-l-2 border-line pl-4 text-[15px]">
            {SECTIONS.map(([id, label]) => <li key={id}><a href={`#${id}`} className="text-ink-2 hover:text-ink">{label}</a></li>)}
          </ul>
        </nav>

        <div className="min-w-0 max-w-[70ch]">
          <H2 id="methods">How the water is read</H2>
          <P><b>Where water used to be.</b> The JRC Global Surface Water record classifies every 30 m Landsat pixel from 1984 to 2020. A pixel that held water in at least 5% of clear observations counts as historic water. Its transition class says whether that water is still there, became seasonal, or was lost. Water bodies are the connected patches of historic water larger than 2 ha (0.5 to 1 ha in the hill and delta areas), split into lakes and river stretches by shape. Sea water is removed using elevation.</P>
          <P><b>How full each lake got, every year.</b> For each monsoon season since 1987 JalSmriti picks the clearest post-monsoon scenes: Landsat 4 to 9 until 2015, Sentinel-2 from 2016. A pixel is water when the modified normalised difference water index (MNDWI) is above 0 and short-wave infrared reflectance is below 0.10, or when the Sentinel-2 scene classifier calls it water. A look counts for a lake only if at least 90% of the lake is clear, with no cloud or shadow within 150 m. That gives a water spread for every season: the bars on each lake page.</P>
          <P><b>What replaced the lost water.</b> Impact Observatory's 10 m annual land cover (2017 to 2023) says what the lost water became: built-up, bare ground, crops or vegetation. An old lake bed counts as built over only where it is built-up in the latest years. ESA WorldCover 2021 is kept as a second opinion.</P>
          <P><b>How the ground drains.</b> From the 30 m Copernicus elevation model, JalSmriti fills depressions (priority flood) to find bowls where rain ponds, traces D8 drainage lines, and measures each pixel's height above the nearest drainage line (HAND).</P>
          <P><b>Floods seen by radar.</b> Sentinel-1 radar sees through monsoon cloud. Since 2017, each pass over a place is compared with the same orbit in other years within 20 days of the same date. Water that is dark (below −18 dB, VV) and at least 3 dB darker than usual for that time of year is unusual standing water. Comparing with the same season is what keeps flooded paddy fields from looking like floods. At least 0.24 ha within 300 m counts as a sighting.</P>
          <P><b>Rain.</b> NASA POWER's corrected monthly precipitation gives each lake its monsoon total for every season. Only complete seasons are used.</P>
          <P><b>The latest look.</b> The newest Sentinel-2 scene of the last 120 days that sees the lake clearly gives the current open water, the share choked by floating weeds (vegetation with NDVI above 0.35 inside the usual water spread) and a colour index that can point to algal blooms.</P>

          <H2 id="grade">The lake grade</H2>
          <P>The grade is four parts of 25 points each, added up and banded: A from 80, B from 65, C from 50, D from 35, E below. A part with no data is left out and the others are rescaled.</P>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-[16.5px] leading-[1.6]">
            <li><b>Water held now.</b> The median water spread of the four most recent seasons, against the median of seasons before 2011 that had monsoon rain within 25% of the same total. Holding as much as then earns all 25 points.</li>
            <li><b>Old lake bed still open.</b> Full points with nothing built on the historic spread, none once 30% is built over.</li>
            <li><b>Open water surface.</b> Full points with no floating weeds, none at 60% weed cover.</li>
            <li><b>Water spread kept since 1984.</b> Full points with no water lost, none once half of it is gone.</li>
          </ul>
          <P>Storage lost is the lost spread times an assumed depth of 1 to 2 m. It is a range on purpose: depths are not measured.</P>

          <H2 id="validation">Water memory, tested</H2>
          <P>A place check compares five signals with 240 random built-up places in Bengaluru, Chennai, Hyderabad and Delhi: the deepest hollow within 300 m, old water beds built over within 2 km, water lost within 1 km, water ever seen within 1 km, and the lowest height above a drainage line within 300 m. The water memory index is the average of the five percentile ranks, with equal weights that were never fitted to the test. Strong is 70 or more, some is 45 to 70, little is below 45. A radar sighting lifts a place by one tier.</P>
          <P>To test it, we collected 39 localities reported flooded in widely covered events: Bengaluru in 2022, Chennai in 2015 and 2023, Hyderabad in 2020, and Delhi and Gurugram in 2023. Each point is a locality centre, not the exact flooded street. Pick one flooded locality and one random built-up place: the flooded one has the higher index 68.5% of the time (AUC 0.685, where 0.5 would be chance).</P>
          <TierChart />
          <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
            {CITY_AUC.map(([c, v]) => (
              <div key={c}>
                <div className="muted text-[14px]">{c}</div>
                <div className="num text-[1.9rem] leading-none">{v.toFixed(2)}</div>
              </div>
            ))}
          </div>
          <p className="muted mt-2 text-[13.5px]">AUC by city.</p>
          <P>It works best in Bengaluru, a city built over its tanks, and on Delhi's Yamuna floodplain. It is weak in Chennai and Hyderabad, where the worst floods came from extreme rain and breached lakes, and spread far beyond any old water bed. So read the index as history and terrain: a place with strong water memory deserves questions before you buy or build, and a place with little memory can still flood. The test data and script are in the repository (docs/validation-data).</P>

          <H2 id="our-read">Our read for renters and buyers</H2>
          <P>Someone about to rent or buy a home answers four quick questions on the place page: renting or buying, which floor, a car in basement parking, and elderly people or small children at home. JalSmriti then gives a clear verdict: look elsewhere, think twice, fine with checks, or good to go. With it come why, what is in the place's favour, what is against it, and what to do if you still like it. The answers stay on your device; if you download the signed report, they go into it and the signature covers the verdict too.</P>
          <P><b>How it is decided.</b> By fixed points, not by an AI. The place's water memory gives 4 points for strong, 3 for some and 0 for little. The spot having been water in at least 5% of satellite looks from 1984 to 2020 adds 3 (4 from 20%). Low ground or a hollow adds 1, both together add 2, and a hollow 3 m deep adds one more. Old lakes built over within 2 km (5 ha or more) add 1. Radar sightings add 2 (3 from three sightings), and standing water reported by people within 1 km in the last year adds 1 (2 from three reports). Then the family: a first or second floor takes away 2, a third floor or above 3, an independent house adds 1. Basement parking adds 2 and elderly people or small children add 1 once the place itself scores 3 or more. Buying adds 1 where there is an old lake bed at or near the spot, for the legal risk. From 8 points the verdict is look elsewhere, 5 to 7 think twice, 2 to 4 fine with checks, and 1 or less good to go. A place that scores 3 or more on its own is never good to go, whatever the floor, because the street, the basement and the power still go under. A flat on the third floor or above is never look elsewhere: the family can be stranded there, but not flooded.</P>
          <P><b>Tested.</b> For a family renting a ground-floor flat, the verdict says think twice or look elsewhere at 82% of the 39 localities reported flooded, against 52% of the 240 random built-up places (radar left out). Look elsewhere is three times as common at the flooded ones: 15% against 5%. So a warning means "check before you sign", not "never live here". The Past floods page runs the same verdict on 16 places that flooded between 2020 and 2026.</P>
          <P><b>Not advice.</b> It is a reading of open satellite records and your answers, not a survey, a legal opinion or financial advice. Visit after heavy rain, ask neighbours and check the records before you sign.</P>

          <H2 id="this-week">What to do this week</H2>
          <P>A place check ends with steps for this week, in two lists: one for someone about to rent or buy, one for someone who already lives there. The home page asks "What brings you here?" and opens the matching list; the place page switches between them.</P>
          <P><b>Where the steps come from.</b> Each step follows from the place's own record by a fixed rule, not from an AI. Dates when monsoon radar saw standing water become questions to ask about those days. Strong water memory, ground less than 1 m above a drainage line or a hollow 1 m deep or more add advice about floors, basements and plinths. Old lake beds built over nearby (1 ha or more within 2 km) add a check of the land's survey number against the village map and the lake's full tank level. Ground that reaches 42 °C on summer mornings adds advice about shade and roofs. A list has at most seven steps, and your ticks stay on your device.</P>
          <P><b>The same steps everywhere.</b> The place page, the signed report and the narration take the steps from the same rules and say them in the same words, in your language.</P>
          <P><b>The signed report.</b> The place report is a PDF of one or two pages for the reader you chose: what the place remembers, the time-lapse, radar, summer heat, standing water people reported nearby, this week's steps and, for someone renting or buying, four questions for the owner or seller. It is signed with the same AWS KMS key as the dossiers, and its verify page checks it in your browser: change one byte of the PDF and the check fails.</P>
          <P><b>Listening.</b> Place and lake reports can be read aloud in Hindi or English by Amazon Polly, with the neural voice Kajal. Each text becomes audio once and is kept, so playing it again costs nothing.</P>

          <H2 id="rain">Rain heads-up</H2>
          <P>Follow a place and JalSmriti emails you when heavy rain is forecast there for today or tomorrow. Every morning at 06:15 India time, a scheduled job reads the forecast for every followed place from Open-Meteo, which blends national and global weather models at about 10 to 25 km.</P>
          <P><b>When you get an email.</b> Rain is graded with the India Meteorological Department's categories for a day: light from 2.5 mm, moderate from 15.6 mm, heavy from 64.5 mm, very heavy from 115.6 mm and extremely heavy from 204.5 mm. Every followed place gets a heads-up for heavy rain. Places with a water memory flood with less, so they get one earlier: strong water memory from 35 mm in a day or 15 mm in one hour, some water memory from 50 mm in a day or 20 mm in one hour. These are working thresholds, not fitted to flood records.</P>
          <P><b>The email.</b> It says how much rain is expected, how heavy the worst hour may be, the chance of rain, why this place floods and four things to do before the rain, in the language you chose. A rainy day is announced once, and a place gets at most one email a day. Each person has their own Amazon SNS topic, so you confirm your address once however many places you follow (up to ten). You can send yourself a test email from My activity.</P>
          <P><b>Not an official warning.</b> Forecasts can be wrong, and rain in your street can be heavier or lighter. Warnings from IMD and the National Disaster Management Authority (in Nepal, DHM and NDRRMA) come first. The place page also shows the next three days.</P>

          <H2 id="heat">Summer heat</H2>
          <P>Lost lakes make streets hotter as well as wetter. A place check measures how hot the ground gets on summer mornings before the monsoon, and compares it with built-up ground, lake water and trees nearby.</P>
          <P><b>How it is measured.</b> Landsat 8 and 9 carry a thermal sensor that measures the temperature of the surface itself: roofs, roads, soil, tree canopy and water. JalSmriti looks at the passes between 15 March and 31 May of the last three summers with less than 30% cloud, keeps up to 8 of the clearest, spread over the three summers, leaves out cloudy pixels and anything outside 5 to 75 °C, and takes the median of each pixel. "Here" is the median within 300 m of the place. It is compared with the medians over built-up ground and trees (Impact Observatory land cover, 2023) and over water that was there in at least half of all observations from 1984 to 2020, in a window 6 km across.</P>
          <P><b>Reading it.</b> Landsat passes at about 10:30 to 11:00 in the morning, so afternoons are hotter still, and this is the ground, not the air. The thermal pixels are 100 m across, so a pond smaller than that reads warm, mixed with the ground around it. At least two clear passes are needed; in cloudy places there may not be enough.</P>

          <H2 id="standing-water">Standing water from people</H2>
          <P>Satellites miss water that drains in hours; people standing in it do not. Anyone signed in can report standing water with a photo, the location and how deep it is: ankle, knee, waist or above car wheels. Reports appear on a live map of the last 48 hours or 7 days, and a place page counts the reports within 1 km in the last year.</P>
          <P><b>Checks.</b> A report goes through the same privacy steps as lake photos: the original is fingerprinted and kept private, Amazon Rekognition holds back unsafe photos and finds faces, which are blurred, and the public copy carries no phone metadata. The photo's own location is used when it has one, otherwise the phone's; if the two are more than 2 km apart the photo wins and the report is flagged. A photo taken more than 48 hours before it was sent is marked as old.</P>
          <P><b>AI and people.</b> Amazon Nova looks at the photo and says whether standing water is visible and how deep, in one plain sentence. That is a hint, never a verdict: a report goes on the map at once unless Nova is at least 60% sure there is no water, and then it waits for a verifier. NGO verifiers in the area confirm or reject reports with a note, under the access rules below, and nobody can review their own report.</P>

          <H2 id="lake-causes">Why a lake is like this</H2>
          <P>Each lake page reads the likely causes of its state from its own record, most serious first, and says what each one rests on. <b>Built on its bed</b>: buildings and roads on the old lake bed, from Sentinel-2 land cover over the 1984 to 2020 water history. <b>Filled in or drying out</b>: lost water spread that is now bare ground. <b>Covered by plants</b>: lost water spread that now shows as plants from space. That can be scrub, fields or a thick mat of water hyacinth, which land-cover maps often call crops, so when the open water is choked with weeds too the page says that is the likely reading. <b>Less water reaches it</b>: in recent monsoons it held under 80% of what it held in past years of similar rain. <b>Choked by weeds and algae</b>: 20% or more of the water under floating weeds, or an algal colour, on the latest clear Sentinel-2 image; both feed on nutrients, usually untreated sewage. <b>Holding up</b>: none of these.</P>
          <P><b>What would help.</b> Each cause brings actions for residents (photographs with location on, the RTI request, watching the lake, a signed dossier, checking a home before renting nearby, walking the inflow channels after rain, reporting sewage) and asks for the authorities (survey and mark the boundary and buffer, remove buildings on the bed, reconnect the inflow channels and desilt, stop debris dumping, stop sewage and run the treatment plants, remove weeds regularly). The page also says how much monsoon water the lost spread would hold again if restored, 1 to 2 m deep.</P>
          <P><b>In the news.</b> Recent headlines naming the lake come from Google News search, over the past year, and from the GDELT Project's open index of world news when Google News does not answer (GDELT covers the last three months and is asked at most once every five seconds across the whole site). Simple keywords tag each headline as flooding, encroachment, pollution or restoration, and only tagged headlines are shown, so a crime story that happens to name the lake is left out. Each answer is kept for 12 hours, and each article stays on its publisher's site. A water body without a name of its own has no news to search for.</P>
          <P><b>Names.</b> A water body that no map names (OpenStreetMap through Photon, then GeoNames) is named after what is near it: the nearest named lake within 2 km ("Water body near Bellandur Lake" within 1 km, "Water body 1.9 km south of Agara Lake" beyond), else its locality, else the nearest named lake within 6 km, else a neighbour's locality, else the area. Where two get the same name, the side of the lake tells them apart. The lake page says where each name came from.</P>

          <H2 id="evidence">Evidence and dossiers</H2>
          <P><b>Photos.</b> A photo goes straight from the phone to a private Amazon S3 bucket. A queue then hands it to a function that fingerprints the original (SHA-256), reads its time and GPS and checks the GPS against the lake outline: within 30 m is "at the lake", within 400 m is "near". Amazon Rekognition screens it for unsafe content and finds faces, which are blurred in the public copy. The public copy carries no phone metadata. <b>Is it the lake at all?</b> Three independent checks keep out screenshots, documents, posters, drawings and photos of something else: Rekognition counts the printed words it can read (25 or more with no outdoor scene means a screenshot or document), Rekognition's labels (a poster, a document, a drawing, and no outdoor scene), and Amazon Nova, asked whether this is a real photograph taken at a lake, its banks or the land around it. Such an upload is kept private with the reason, never reaches the public page, the verifiers or the ledger, and the uploader is told why. When Nova says no but Rekognition sees water, a verifier decides. Amazon Nova also describes what the photo shows in fixed categories (dumping, sewage, construction and so on); that description is a hint for the verifier, never a verdict.</P>
          <P><b>Review.</b> An NGO verifier for the area confirms or rejects each photo with a note. The rules below decide who may do that, and every decision goes into the lake's ledger.</P>
          <P><b>The dossier.</b> The code computes the facts first. An agent built with Strands Agents on Amazon Bedrock (Amazon Nova) then drafts a formal letter, reading those facts through three tools. Every number in its draft must appear in the facts; if one does not, the draft is redone, and after repeated failures a fixed template is used instead. Amazon Translate makes the second language (Nepali, Assamese and Odia go through Amazon Nova), and the numbers are checked again after translation. The PDF carries the facts, the time-lapse, the photos and both letters.</P>
          <P><b>Signature and ledger.</b> JalSmriti writes a short statement with the dossier's content fingerprint, the PDF fingerprint and the time, and signs it with an ECDSA P-256 key held in AWS KMS: the private key cannot be exported, even by the operator. Anyone can check the signature in the browser on the dossier's verify page. Each lake also has an append-only hash chain of photos, reviews, dossiers, submissions and responses; changing an old entry breaks every hash after it.</P>
          <P><b>Right to Information.</b> A lake page drafts a request for the lake's official records under India's Right to Information Act 2005 or Nepal's Right to Information Act 2007: survey numbers and the full tank level boundary, encroachments and the action taken, building permissions, works and complaints. You can copy, download or print it. If you record that you filed it, the lake's ledger shows the filing and the date a reply is due: 30 days in India, 15 in Nepal.</P>

          <H2 id="rules">Access rules</H2>
          <P>Reading is open to everyone. Every write, and every look at a review queue or audit log, is decided by Cedar, the open-source policy language from AWS. The decision and the rule that made it are written to the area's audit log, denials included.</P>
          {pol && (
            <>
              <ul className="mt-4 space-y-2 text-[16px]">
                {Object.entries(pol.rules).map(([id, text]) => (
                  <li key={id} className="grid gap-x-4 sm:grid-cols-[17rem_minmax(0,1fr)]">
                    <code className="text-[13.5px] text-memory">{id}</code><span>{text}</span>
                  </li>
                ))}
              </ul>
              <details className="mt-5">
                <summary className="cursor-pointer text-[15px] font-semibold">The policies as written</summary>
                <pre className="mt-3 max-h-[28rem] overflow-auto rounded-lg bg-paper-2 p-4 font-mono text-[12.5px] leading-relaxed">{pol.cedar}</pre>
              </details>
            </>
          )}

          <H2 id="privacy">Privacy</H2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-[16.5px] leading-[1.6]">
            <li>You appear everywhere under a pseudonym such as "Citizen 7F3A". Your email is used to sign in and for alerts you ask for, and is never shown.</li>
            <li>Faces are blurred and phone metadata is removed before a photo is public. Exact photo locations are checked, not published.</li>
            <li>Originals stay in a private bucket, kept with their fingerprints so a dossier can be backed by them.</li>
            <li>Place checks need no account. A check is cached by area (about 150 m), not by person.</li>
            <li>Standing-water reports are shown at about 11 m precision, under your pseudonym. The exact position and the photo's metadata stay private.</li>
            <li>Rain heads-ups reach you through your own Amazon SNS topic, whose name is a code that says nothing about you.</li>
            <li>Officials' actions are logged with their pseudonym, role and the deciding rule.</li>
          </ul>

          <H2 id="limits">Limits</H2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-[16.5px] leading-[1.6]">
            <li>Pixels are 10 to 30 m. Ponds smaller than about half a hectare, narrow drains and thin channels are missed.</li>
            <li>Outlines are approximate. They are not a land survey and cannot settle a boundary dispute; revenue and survey records do that.</li>
            <li>The historic record ends in 2020. Change after that comes from the seasonal looks and the latest look.</li>
            <li>Land cover maps are model outputs with their own errors, especially between bare ground and built-up.</li>
            <li>Radar cannot see water between tall buildings, and one radar pass every 6 to 12 days can miss a flood that drains in hours.</li>
            <li>The letter is drafted by AI. Its numbers are checked; its tone and its reading of the law should be checked by you before you submit it.</li>
            <li>Summer heat is the temperature of the ground surface at about 10:30 to 11:00 in the morning, not the air temperature. Afternoons are hotter.</li>
            <li>Rain forecasts come from Open-Meteo and can be wrong. They are not official warnings.</li>
            <li>Standing-water reports are citizen data. Amazon Nova and verifiers check them, but a report can still be wrong or out of date.</li>
            <li>Translations are machine translations.</li>
          </ul>

          <H2 id="data">Data and credits</H2>
          <ul className="mt-4 space-y-2.5 text-[16px] leading-[1.55]">
            <li><b>JRC Global Surface Water</b> 1984-2020, Pekel et al. (2016), European Commission Joint Research Centre. CC BY 4.0.</li>
            <li><b>Landsat 4-9</b> Collection 2 Level-2, including the Landsat 8-9 surface temperature band, courtesy of the U.S. Geological Survey. Public domain.</li>
            <li><b>Sentinel-2 and Sentinel-1</b>: contains modified Copernicus Sentinel data 2016-2026, processed by ESA. Sentinel-2 L2A from Earth Search by Element 84 on the Registry of Open Data on AWS; Sentinel-1 RTC from Microsoft Planetary Computer.</li>
            <li><b>Copernicus DEM GLO-30</b>, © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.</li>
            <li><b>Impact Observatory</b> 10 m annual land use and land cover, with Esri and Microsoft. CC BY 4.0.</li>
            <li><b>ESA WorldCover</b> 2021, © ESA WorldCover project, contains modified Copernicus Sentinel data. CC BY 4.0.</li>
            <li><b>NASA POWER</b> monthly precipitation, NASA Langley Research Center POWER Project.</li>
            <li><b>Rain forecasts</b>: weather data by Open-Meteo.com, CC BY 4.0, from its free API for non-commercial use. Rain categories from the India Meteorological Department.</li>
            <li><b>Heat colour ramp</b>: ColorBrewer RdYlBu by Cynthia A. Brewer, Apache License 2.0.</li>
            <li><b>Place and water-body names</b>: © OpenStreetMap contributors (ODbL), searched with Photon by Komoot; GeoNames (CC BY 4.0).</li>
            <li><b>News</b>: headlines found through Google News search and the GDELT Project's open index of world news; each article stays on its publisher's site.</li>
            <li><b>Base maps</b>: Amazon Location Service when deployed; OpenFreeMap and OpenStreetMap otherwise; imagery basemap by Esri.</li>
            <li><b>Fonts</b>: Anek by Ek Type and Noto by Google, both under the SIL Open Font License.</li>
          </ul>

          <H2 id="open-source">Open source and AWS</H2>
          <P>JalSmriti uses three open-source projects from AWS: <b>Strands Agents</b> for the letter-drafting agent, <b>Cedar</b> for the access rules, and <b>Powertools for AWS Lambda</b> for the API. Satellite data is read in place with GDAL and rasterio from cloud-optimised files, so no archive is copied. Maps are drawn with MapLibre GL JS and PDFs with fpdf2 and HarfBuzz.</P>
          <P>On AWS, Step Functions with Distributed Map reads a whole city season by season in parallel Lambda functions, and a place check runs four branches at once (history and terrain, time-lapse, radar, summer heat); DynamoDB holds the lakes, evidence, ledgers and audit logs; S3 and CloudFront serve the site, the map layers, the reports and the audio; Cognito handles accounts; Bedrock, Translate, Rekognition and KMS do the drafting, translating, screening and signing; Polly reads reports aloud; SQS, SNS and EventBridge Scheduler run the photo pipeline, the email alerts, the daily rain check and the weekly satellite check; Location Service provides search and maps; CloudWatch watches it all. Everything is one CloudFormation stack that runs on a new account's free tier and credits.</P>
          <H2 id="credit">Who made it</H2>
          <P>JalSmriti was made by <b>Ansh Singhal</b> for WeMakeDevs × AWS Environmental Hacks 2026, in the Heat and Water track.</P>
          <div className="mt-10 flex flex-wrap gap-3">
            <Link className="btn-primary" to="/place">{t("nav.check")}</Link>
            <Link className="btn-quiet" to="/explore">{t("nav.explore")}</Link>
          </div>
        </div>
      </div>
    </div>
  );
}

"""qbharvest — the harvesting policy registry and the automated harvesting engine, shared by the three QueryBook
applications through the Commons database.

  Policy registry  every source a harvest team may read, with its licence, its licence class and its status
                   (approved / blocked / pending). Only classes that put NO condition on QueryBook are approved by
                   default: public domain, CC0, facts (not protected by copyright — QueryBook stores the facts, not
                   anyone's wording), US federal government works, QueryBook's own calculations, and facts the admin
                   entered with their citation. Attribution, share-alike, non-commercial, no-derivatives, someone
                   else's wording, restrictive terms of service and unknown licences are blocked. Parameters
                   (budgets, rotation weights, schedule) live here too, and every change is versioned.
  Engine           decides which application harvests next — alternating language, STEM and history — so that
                   checks one application asked of another are answered on the very next turn, domains that are
                   producing only duplicates back off (less volume), and no domain runs twice in a row while
                   another has work (less waiting).
  Learner          after every turn, compares the measured results (new facts per second, share of new vs
                   duplicate facts, failures, how long checks waited) with the current parameters and RECOMMENDS
                   changes. Nothing it recommends takes effect until the admin approves it with the admin
                   passphrase; approvals and rejections are kept.
  Harvest record   every task — harvested, blocked or skipped — is logged with its source, licence class and the
                   reason it was harvested; each entry carries the hash of the one before (tamper-evident) and the
                   log is archived to monthly JSON-lines files in the Commons folder.

Deterministic programs, not AI models. Standard library only.
"""
import datetime, hashlib, hmac, json, os, secrets

import qbcore as core

ENGINE_VERSION = "1.1.0"

SCHEMA = """
CREATE TABLE policy_sources (
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, name TEXT NOT NULL, apps TEXT NOT NULL, kind TEXT, licence TEXT NOT NULL,
  licence_class TEXT NOT NULL, url TEXT, licence_url TEXT, status TEXT NOT NULL, reason TEXT, added_by TEXT NOT NULL, added TEXT NOT NULL,
  decided_by TEXT, decided_at TEXT
);
CREATE TABLE policy_params (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT, updated TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE policy_versions (id INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, change TEXT NOT NULL, reason TEXT);
CREATE TABLE harvest_log (
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, app TEXT NOT NULL, domain TEXT NOT NULL, action TEXT NOT NULL, title TEXT,
  source_key TEXT, licence_class TEXT, decision TEXT NOT NULL, items INTEGER, new INTEGER, merged INTEGER, seconds REAL,
  reason TEXT, budget_key TEXT, turn_id INTEGER, policy_version INTEGER, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE INDEX harvest_log_app ON harvest_log(app, action, id);
CREATE TABLE recommendations (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, app TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, rationale TEXT NOT NULL,
  evidence TEXT, change TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending',
  decided_by TEXT, decided_at TEXT, note TEXT
);
CREATE TABLE engine_turns (
  id INTEGER PRIMARY KEY, started TEXT NOT NULL, ended TEXT, app TEXT NOT NULL, domain TEXT NOT NULL, reason TEXT, scores TEXT, result TEXT
);
CREATE TABLE app_heartbeat (app TEXT PRIMARY KEY, at REAL NOT NULL, version TEXT);
ALTER TABLE evidence ADD COLUMN harvest_id INTEGER
"""

DOMAIN_OF = {"language": "language", "stem": "stem", "facts": "history"}

# licence class → (allowed by default, why)
LICENCE_CLASSES = {
    "public-domain": (True, "No copyright: free to use with no conditions."),
    "cc0": (True, "Dedicated to the public domain (CC0): no conditions."),
    "facts": (True, "Facts and defined values are not protected by copyright; QueryBook stores the facts, never anyone's wording."),
    "us-federal": (True, "A work of the US federal government: no US copyright (17 U.S.C. § 105)."),
    "computed": (True, "Calculated by QueryBook itself."),
    "user-facts": (True, "Facts the admin entered with their citation; no third-party wording is shared."),
    "attribution": (False, "Requires attribution (e.g. CC BY): a condition on QueryBook."),
    "share-alike": (False, "Share-alike (e.g. CC BY-SA, GFDL): would impose its licence on QueryBook."),
    "non-commercial": (False, "Non-commercial only (e.g. CC BY-NC): restricts how QueryBook may be used."),
    "no-derivatives": (False, "No derivatives (CC BY-ND): forbids adapting the material."),
    "copyrighted-text": (False, "Someone else's wording (articles, headlines, books): protected by copyright."),
    "terms-of-service": (False, "Website or API terms restrict reuse."),
    "unknown": (False, "The licence has not been established: blocked until the admin classifies it."),
}
# classes whose wording itself may be stored (otherwise only the facts are kept and quotes are dropped)
TEXT_FREE = {"public-domain", "cc0", "us-federal", "computed"}

SEED_SOURCES = [
    # key, name, apps, kind, licence, class, url, reason
    ("webster-1913", "Webster's Unabridged Dictionary (1913)", "language", "dictionary", "Public domain (published 1913)", "public-domain",
     "https://www.gutenberg.org/ebooks/29765", "English meanings: out of copyright."),
    ("muse-bilingual", "MUSE bilingual dictionaries (Facebook AI Research)", "language", "word lists", "CC BY-NC 4.0", "non-commercial",
     "https://github.com/facebookresearch/MUSE", "Non-commercial licence: would restrict QueryBook. Replace with an unrestricted source."),
    ("codata-2018", "CODATA 2018 recommended values (NIST)", "stem", "reference table", "Facts / defined values", "facts",
     "https://physics.nist.gov/cuu/Constants/", "Physical constants are measured or defined values (facts)."),
    ("iupac-atomic-weights", "IUPAC standard atomic weights", "stem", "reference table", "Facts", "facts",
     "https://iupac.qmul.ac.uk/AtWt/", "Atomic numbers and weights are facts."),
    ("si-definitions", "SI unit definitions (BIPM SI Brochure, NIST SP 811)", "stem", "reference table", "Facts / defined values", "facts",
     "https://www.bipm.org/en/publications/si-brochure", "Exact unit factors are definitions (facts); no brochure text is copied."),
    ("stem-computed", "QueryBook Math, Science & Engineering calculations", "stem", "computation", "Computed by QueryBook", "computed", None,
     "Molar masses, derived constants and checks calculated here."),
    ("stem-saved-answers", "Verified saved answers (recomputed)", "stem", "computation", "Computed by QueryBook", "computed", None,
     "The admin's own calculations, recomputed before sharing."),
    ("history-user-sources", "Facts entered in History & News with their sources", "facts", "user records", "Facts with citation", "user-facts", None,
     "Facts and dates are not copyrightable; the citation is kept, quotes from the source are not shared."),
    ("news-headlines", "News feed headlines", "facts", "news feeds", "Publishers' copyright", "copyrighted-text", None,
     "Headlines are the publishers' wording: not harvested. Add a fact by hand with its source instead."),
]

# Sources researched for the seven new subjects (October 2026 web research of each publisher's own terms).
# None is approved automatically: the ones whose licence class is unrestricted enter the registry as *pending*
# with a recommendation for the admin; the restricted ones enter *blocked*, with the reason, so they are not
# researched again. Each note records the evidence and the limits of the approval.
RESEARCHED_SOURCES = [
    # key, name, apps, subjects, licence as stated, class, url, note
    ("wikidata", "Wikidata (structured data)", "language,stem,facts", "all seven subjects", "CC0 1.0 (main, property and lexeme namespaces)", "cc0",
     "https://www.wikidata.org/wiki/Wikidata:Licensing",
     "Wikidata's licensing page: structured data is CC0. Only items and statements; its free-text pages are CC BY-SA and are not used. "
     "Covers chemistry (compounds, elements), architecture (buildings, architects, styles), geography (places, coordinates), programming "
     "languages, mathematics, civil-engineering works and quantum-computing concepts."),
    ("pubchem-computed", "PubChem computed properties (NCBI, US National Library of Medicine)", "stem", "chemistry",
     "US government work (NLM); depositor records may carry their own rights", "us-federal", "https://pubchem.ncbi.nlm.nih.gov/",
     "NLM states its government information is public domain, but PubChem also holds material contributed by depositors that may be "
     "copyrighted. Approve for NCBI-computed properties only (formula, molecular weight, identifiers) — never depositor text."),
    ("natural-earth", "Natural Earth map data", "facts", "geography", "Public domain", "public-domain", "https://www.naturalearthdata.com/about/terms-of-use/",
     "Natural Earth's terms: all raster and vector data are public domain, no permission or attribution needed. Countries, capitals, "
     "rivers, lakes and their coordinates."),
    ("usgs-gnis", "USGS Geographic Names Information System (GNIS)", "facts", "geography", "US government work (public domain)", "us-federal",
     "https://www.usgs.gov/us-board-on-geographic-names/download-gnis-data",
     "Official US place and feature names with coordinates; metadata states 'Limitations of use: None (Public Domain Information)'."),
    ("census-gazetteer", "US Census Bureau Gazetteer files", "facts", "geography", "US government work", "us-federal",
     "https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html",
     "Places, counties and their areas and coordinates. 'TIGER' is a Census Bureau trademark: use the facts, not the name as a brand."),
    ("world-factbook-2020-archive", "CIA World Factbook (archived edition)", "facts", "geography", "US government work", "us-federal",
     "https://github.com/simonw/cia-world-factbook-2020",
     "The CIA ended the Factbook on 4 February 2026 and took the site down; archived editions remain public domain. Facts must be stored "
     "'as of' their edition year — never as current."),
    ("habs-haer-hals", "Historic American Buildings / Engineering Record / Landscapes Survey (NPS, Library of Congress)", "facts,stem",
     "architecture, civil engineering", "US government work; some items credit a third party", "us-federal",
     "https://www.nps.gov/subjects/heritagedocumentation/collection.htm",
     "NPS: material created for HABS/HAER/HALS is public domain (46,000+ sites: buildings, bridges, dams, canals). Skip any item with a "
     "credit line naming another source — those may need permission."),
    ("vitruvius-1914", "Vitruvius, The Ten Books on Architecture (M. H. Morgan translation, 1914)", "facts", "architecture",
     "Public domain in the US (published 1914)", "public-domain", "https://www.gutenberg.org/ebooks/20239",
     "Out of copyright in the US. Taken from Project Gutenberg: its licence and trademark wrapper must be stripped (Gutenberg says the "
     "remaining text is then unrestricted in the US)."),
    ("gutenberg-pre1931", "Public-domain textbooks from Project Gutenberg (published before 1931)", "language,stem,facts",
     "mathematics, architecture, engineering, chemistry", "Public domain in the US; Gutenberg wrapper removed", "public-domain",
     "https://www.gutenberg.org/policy/license",
     "Each book's own Gutenberg header must say it is not restricted by US copyright; strip the licence and every 'Project Gutenberg' "
     "reference. Old textbooks give definitions and theorems; check facts against current science before trusting them."),
    ("nist-dads", "NIST Dictionary of Algorithms and Data Structures", "stem", "computer programming", "Public domain (17 U.S.C. § 105), except CRC Press entries",
     "us-federal", "https://xlinux.nist.gov/dads/Other/creditNotice.html",
     "NIST's credit notice: entries by federal employees are public domain; a subset belongs to CRC Press — skip entries marked as CRC."),
    ("fhwa-federal-authored", "FHWA reports written by federal employees", "stem", "civil engineering", "US government work (only federal-authored)",
     "us-federal", "https://highways.dot.gov/research",
     "FHWA guidance: work by federal employees is not copyrighted; contractor reports and borrowed figures vary. Approve only documents "
     "whose front matter shows federal authorship."),
    ("usace-engineering-manuals", "US Army Corps of Engineers manuals and regulations (EM, ER, EC)", "stem", "civil engineering",
     "US government work; 'Approved for public release; distribution is unlimited'", "us-federal", "https://www.publications.usace.army.mil/",
     "Harvest only documents carrying the public-release statement (hydraulics, coastal engineering, geotechnics, structures). Some "
     "chapters are superseded — keep each fact's document date."),
    ("nist-pqc-fips", "NIST post-quantum cryptography standards (FIPS 203, 204, 205)", "stem", "quantum computing",
     "US government work (published 13 August 2024)", "us-federal", "https://csrc.nist.gov/projects/post-quantum-cryptography",
     "Parameter sets, key sizes and algorithm names. The standards' text is federal; the algorithms' patent statements are on NIST's "
     "'PQC License Summary' page — read it before any implementation use."),
    ("arxiv-cc0", "arXiv papers released under CC0 only", "stem", "quantum computing, mathematics, computer science", "CC0 (author's choice, per paper)",
     "cc0", "https://info.arxiv.org/help/license/",
     "arXiv licences are chosen per paper and irrevocable. Only papers marked CC0 qualify; CC BY, CC BY-SA, CC BY-NC and arXiv's "
     "default distribution licence are all excluded paper by paper."),
    # second round (all areas of language, STEM and history)
    ("tatoeba-cc0", "Tatoeba example sentences — the CC0 subset only", "language", "language (example sentences)",
     "CC0 1.0 for sentences their authors marked CC0; everything else CC BY 2.0 FR", "cc0", "https://tatoeba.org/en/downloads",
     "Only original sentences explicitly marked CC0 (Tatoeba publishes them as a separate download). Translations and audio are not CC0 "
     "and are excluded, so this gives example sentences per language, not translation pairs."),
    ("common-voice-text", "Mozilla Common Voice sentence collection (text)", "language", "language (sentences in 100+ languages)",
     "CC0 (Mozilla accepts only CC0 source text)", "cc0", "https://github.com/common-voice/common-voice",
     "Use the sentence text from the open-source repository. The packaged speech datasets add terms (no re-hosting, no identifying "
     "speakers) and are not taken."),
    ("fsi-courses", "US Foreign Service Institute language courses", "language", "language (40+ languages: grammar, drills, vocabulary)",
     "US government work (as stated by the hosting sites)", "us-federal", "https://fsi-language-courses.org/",
     "Courses written by the State Department's FSI. They are hosted only by unofficial mirrors; the public-domain status is stated by "
     "those sites, not confirmed by an official page — verify each course's title page shows federal authorship."),
    ("nasa", "NASA science and education material", "stem", "astronomy, space, earth science, physics",
     "Generally not copyrighted in the US (NASA media guidelines)", "us-federal", "https://www.nasa.gov/nasa-brand-center/images-and-media/",
     "Exclude the NASA insignia and logos, items marked as third-party copyright, and material from non-US space agencies."),
    ("noaa", "NOAA data (weather, climate, oceans)", "stem,facts", "earth science, geography, climate history",
     "Public domain unless annotated otherwise", "us-federal", "https://psl.noaa.gov/disclaimer",
     "NOAA: server information is public domain unless annotated. Exclude annotated products and production software; facts only."),
    ("usda-fooddata-central", "USDA FoodData Central", "stem", "chemistry and biology (food composition)", "CC0 1.0", "cc0",
     "https://fdc.nal.usda.gov/", "USDA: the data are public domain, not copyrighted, published under CC0. Nutrients per food."),
    ("ncbi-taxonomy", "NCBI Taxonomy", "stem", "biology (classification of organisms)", "US government work (NCBI policy)", "us-federal",
     "https://www.ncbi.nlm.nih.gov/home/about/policies/", "NCBI-created information is public domain; the taxonomy names and ranks are "
     "facts. Skip anything NCBI attributes to another rights holder."),
    ("smithsonian-open-access", "Smithsonian Open Access", "stem,facts", "natural history, science, art and history", "CC0 1.0 (items marked CC0)",
     "cc0", "https://www.si.edu/openaccess", "5 million+ items from 19 museums and 9 research centres, with data via API and GitHub. "
     "Only items marked CC0."),
    ("nara-catalog", "US National Archives Catalog", "facts", "US history (records, dates, people)", "Federal records: not copyrighted",
     "us-federal", "https://www.archives.gov/faqs",
     "Only records whose use-restriction field is 'Unrestricted'. Donated materials can carry copyright or deed restrictions — skipped. "
     "NARA does not certify status, so the restriction field is the gate."),
    ("chronicling-america-pre1931", "Chronicling America historic newspapers, titles over 95 years old", "facts,language",
     "history (dated events), historical language", "Public domain (cleared in their entirety by the Library of Congress)", "public-domain",
     "https://www.loc.gov/collections/chronicling-america/about-this-collection/rights-and-access/",
     "Titles more than 95 years old are cleared in full; newer issues can contain protected material and are not taken. Facts are kept "
     "with the paper's date — a newspaper report is 'reported', not confirmed."),
    ("frus", "Foreign Relations of the United States (State Department Office of the Historian)", "facts", "diplomatic history since 1861",
     "US government work", "us-federal", "https://history.state.gov/open/frus-metadata",
     "Nearly 500 volumes of documents with open metadata (XML). Dates, participants and events."),
    ("army-cmh", "US Army Center of Military History publications", "facts", "military history", "US government work (17 U.S.C. § 105)",
     "us-federal", "https://history.army.mil/", "Federal histories and unit lineages. Check each title for third-party photographs or art, "
     "which can have their own copyright."),
    ("europeana-metadata", "Europeana metadata", "facts,language", "European history, art and culture (60+ million records)", "CC0 (metadata)",
     "cc0", "https://pro.europeana.eu/page/the-data-exchange-agreement",
     "All metadata is published under CC0 by agreement with the providers. The objects themselves (images, texts) carry their own "
     "rights statements and are not taken — only the record facts."),
    ("dpla-metadata", "Digital Public Library of America metadata", "facts", "US history and culture", "CC0 (metadata)", "cc0",
     "https://pro.dp.la/hubs/metadata-application-profile", "Partners dedicate their metadata to the public domain under CC0; the linked "
     "items have their own rights and are not taken."),
    ("met-open-access", "The Metropolitan Museum of Art Open Access data", "facts", "art history (titles, artists, dates, media)", "CC0",
     "cc0", "https://www.metmuseum.org/policies/image-resources", "Basic metadata for the whole online collection is CC0, including works "
     "still in copyright (only the data, not their images). Bulk CSV on GitHub and a JSON API."),
    # (1.47) more sources researched — unrestricted ones enter pending with a recommendation; restricted ones blocked with the reason
    ("usgs-earthquakes", "USGS Earthquake Hazards Program — earthquake catalog (ComCat)", "stem,facts", "earth science (earthquakes since 1900)",
     "US government work (USGS data are in the US public domain)", "us-federal", "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
     "USGS policy: USGS-authored or produced data and information are in the US public domain. The FDSN event web service is open, "
     "no key. Facts only: magnitude, time, place name, coordinates, depth. Contributed network data are part of the catalog record."),
    ("federal-register", "Federal Register (Office of the Federal Register, National Archives)", "facts", "US history (executive orders, proclamations, rules)",
     "US government work; no restrictions on republication", "us-federal", "https://www.federalregister.gov/reader-aids/understanding-the-federal-register",
     "The Federal Register is a federal publication with no restrictions on republication; its API is open, no key. Facts only: "
     "document titles, numbers, signing and publication dates, issuing president or agency."),
    ("world-bank-indicators", "World Bank Open Data (indicators)", "facts,stem", "economics and development statistics",
     "CC BY 4.0", "attribution", "https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets",
     "Requires attribution (a condition on QueryBook): blocked unless the admin accepts the attribution condition."),
    ("openstreetmap", "OpenStreetMap", "facts", "geography (places, roads, buildings)", "ODbL 1.0", "share-alike",
     "https://www.openstreetmap.org/copyright", "Open Database Licence is share-alike for derived databases: blocked. Natural Earth, "
     "GNIS and Wikidata cover the same geography without conditions."),
    ("geonames", "GeoNames gazetteer", "facts", "geography (place names, populations)", "CC BY 4.0", "attribution",
     "https://www.geonames.org/about.html", "Attribution required: blocked. Wikidata and Natural Earth give place facts under CC0 / public domain."),
    ("wiktionary", "Wiktionary", "language", "dictionary (meanings, pronunciations)", "CC BY-SA 4.0 and GFDL", "share-alike",
     "https://en.wiktionary.org/wiki/Wiktionary:Copyrights", "Share-alike: blocked. Webster 1913 (public domain) and Wikidata lexemes (CC0) instead."),
    ("google-generative-exemplars", "Google Gemini API — generated exemplars (Omni, Veo, TTS, image, text)", "language",
     "learning objects (talking-face video, speech, mouth-shape stills, drill texts)",
     "Output not claimed by Google; Gemini API terms (paid tier): no use to develop competing models", "terms-of-service",
     "https://ai.google.dev/gemini-api/terms",
     "Not a fact source: generated examples become exemplars (learning objects), never Fact Units. Used only by the admin's generator "
     "tool outside the applications, on the paid tier, each tool switched on by the admin. Narrow use: examples for QueryBook's own "
     "engines, never a general model built from Gemini output. Counsel to confirm the competing-models reading."),
    ("rijksmuseum-open-data", "Rijksmuseum open data", "facts", "Dutch and European history and art", "CC0 (museum policy)", "cc0",
     "https://www.rijksmuseum.nl/en/data/policy", "The museum waives copyright and database rights with CC0; some third-party listings say "
     "CC BY — follow the museum's own policy and each object's licence field. Use the download, not a keyed API with its own terms."),
    ("wiktionary", "Wiktionary", "language", "language (definitions, etymology, translations)", "CC BY-SA 4.0 / GFDL", "share-alike",
     "https://en.wiktionary.org/wiki/Wiktionary:Copyrights", "Share-alike: would impose its licence. Wikidata lexemes (CC0) cover part of the same ground."),
    ("princeton-wordnet", "Princeton WordNet", "language", "language (English word senses and relations)", "WordNet licence (notice must be kept)",
     "attribution", "https://wordnet.princeton.edu/license-and-commercial-use", "Permissive, but its copyright notice must accompany copies — a condition."),
    ("panlex", "PanLex translation database", "language", "language (translations across thousands of languages)",
     "Conflicting: download README says CC0, licence page says CC BY-NC-SA 4.0", "unknown", "https://panlex.org/license/",
     "The two official statements contradict each other. Blocked until PanLex confirms CC0 in writing; then reclassify as cc0."),
    ("wikipedia-text", "Wikipedia article text", "language,stem,facts", "all areas", "CC BY-SA 4.0 / GFDL", "share-alike",
     "https://meta.wikimedia.org/wiki/Terms_of_use", "Share-alike for the wording. Use Wikidata (CC0) for the same facts."),
    ("ck12", "CK-12 FlexBooks", "stem", "mathematics and science (K-12)", "CK-12 Curriculum Materials License / CC BY-NC", "non-commercial",
     "https://www.ck12.org/", "Non-commercial or CK-12's own licence depending on the copy."),
    ("saylor-academy", "Saylor Academy courses", "stem,facts", "all areas (college courses)", "CC BY 3.0 for course framing; third-party resources vary",
     "attribution", "https://saylor.org/open/licensinginformation", "Attribution required, and most course content is curated from third "
     "parties under their own terms."),
    ("libretexts", "LibreTexts", "stem", "chemistry, physics, mathematics, biology, engineering", "Per page (many CC BY-NC-SA)", "unknown",
     "https://libretexts.org/", "No site-wide licence: each page states its own, often non-commercial. Blocked as a whole."),
    ("openstreetmap", "OpenStreetMap", "facts", "geography (streets, buildings, places)", "ODbL 1.0", "share-alike",
     "https://wiki.openstreetmap.org/wiki/Open_Database_License", "Share-alike for databases: mixing OSM data would put QueryBook's facts under the ODbL."),
    # first round: researched and blocked: they restrict QueryBook
    ("openstax", "OpenStax textbooks (Rice University)", "stem", "chemistry, mathematics, physics", "CC BY 4.0", "attribution",
     "https://openstax.org/", "CC BY 4.0: free but attribution is a condition (and some adaptations are CC BY-NC-SA)."),
    ("mit-ocw", "MIT OpenCourseWare", "stem", "all subjects", "CC BY-NC-SA 4.0", "non-commercial", "https://ocw.mit.edu/terms",
     "Non-commercial and share-alike; some items are all rights reserved."),
    ("khan-academy", "Khan Academy", "stem", "mathematics, chemistry, computing", "CC BY-NC-SA", "non-commercial",
     "https://support.khanacademy.org/hc/en-us/articles/202262954", "Non-commercial, attribution and share-alike conditions."),
    ("qiskit-textbook", "Qiskit textbook (IBM)", "stem", "quantum computing", "Apache License 2.0", "attribution",
     "https://github.com/Qiskit/qiskit-textbook", "Apache 2.0 requires keeping the licence and notices: a condition on QueryBook."),
    ("oeis", "On-Line Encyclopedia of Integer Sequences", "stem", "mathematics", "CC BY-SA 4.0", "share-alike", "https://oeis.org/",
     "Share-alike. (The sequences themselves are mathematics and can be computed by QueryBook instead.)"),
    ("nist-dlmf", "NIST Digital Library of Mathematical Functions", "stem", "mathematics", "Copyright claimed by NIST", "copyrighted-text",
     "https://dlmf.nist.gov/", "Unusually for a federal site, NIST asserts copyright in the DLMF; formulas can be computed and checked instead."),
    ("nist-webbook", "NIST Chemistry WebBook (Standard Reference Database 69)", "stem", "chemistry",
     "Standard Reference Data: copyright reserved under 15 U.S.C. § 290e", "copyrighted-text", "https://webbook.nist.gov/",
     "NIST Standard Reference Data are an exception to federal public domain; NIST notices say they may not be reproduced without permission."),
    ("python-docs", "Python documentation (Python Software Foundation)", "stem", "computer programming", "PSF License Agreement", "attribution",
     "https://docs.python.org/3/license.html", "Permissive, but the PSF notice must be kept: a condition. Code examples are 0BSD but are code, not facts."),
]

# The admin's own decisions on researched sources, given outside the app (with the date and their words). Applied once
# by Registry.ensure() to sources still pending and never decided in the app — a decision made in the app wins.
ADMIN_DECISIONS = [
    ("2026-10-19", "I approve all the above sources - provided they do not risk copyright issues",
     "approved", ["wikidata", "pubchem-computed", "natural-earth", "usgs-gnis", "census-gazetteer", "world-factbook-2020-archive",
                  "habs-haer-hals", "vitruvius-1914", "gutenberg-pre1931", "nist-dads", "usace-engineering-manuals", "nist-pqc-fips",
                  "arxiv-cc0", "tatoeba-cc0", "common-voice-text", "nasa", "noaa", "usda-fooddata-central", "ncbi-taxonomy",
                  "smithsonian-open-access", "nara-catalog", "chronicling-america-pre1931", "frus", "army-cmh", "europeana-metadata",
                  "dpla-metadata", "met-open-access", "rijksmuseum-open-data"]),
    # held back under the admin's condition: copyright status cannot be checked reliably by a program
    ("2026-10-19", "provided they do not risk copyright issues", "pending", ["fsi-courses", "fhwa-federal-authored"]),
]
HELD_REASON = {
    "fsi-courses": "Held back under the admin's condition (no copyright risk): the courses are only on unofficial mirrors and their "
                   "public-domain status is not confirmed by an official page. Approve by hand after checking a course's title page.",
    "fhwa-federal-authored": "Held back under the admin's condition (no copyright risk): many FHWA reports are written by contractors "
                             "whose copyright varies, and a program cannot tell them apart reliably. Approve by hand per report.",
}

DEFAULT_PARAMS = {
    "rotation.check_weight": (2.0, "How strongly waiting cross-checks pull an application's turn forward"),
    "rotation.repeat_penalty": (5.0, "Penalty for giving the same domain two turns in a row while another has work"),
    "rotation.turn_timeout_s": (900, "A turn not finished within this time is given up (the application may have closed)"),
    "rotation.active_window_s": (180, "An application counts as running if it checked in within this time"),
    "rotation.idle_backoff_max_s": (14400, "Longest pause for a domain that is producing nothing new"),
    "rotation.wait_backoff_max_s": (600, "Longest pause for a domain whose sources asked it to slow down (it is not out of work)"),
    "schedule.tick_s": (30, "How often an idle application asks the engine whether it is its turn"),
    "schedule.busy_tick_s": (3, "How often an application asks while harvesting is under way, so turns follow each other without a gap"),
}


def _now():
    return core.now_cs()


def _hash(prev, row):
    return hashlib.sha256((prev + json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)).encode("utf-8")).hexdigest()


class Registry:
    """The harvesting policy registry (sources, licence classes, parameters, versions)."""

    def __init__(self, commons):
        self.c = commons
        self.store = commons.store

    def ensure(self, app_id=None, budgets=None):
        """Seed the built-in sources and default parameters (never overwriting the admin's decisions); register an
        application's budget defaults as parameters."""
        if self.store.read_only:
            return
        with self.store.write() as db:
            for key, name, apps, kind, lic, cls, url, why in SEED_SOURCES:
                ok = LICENCE_CLASSES[cls][0]
                db.execute("""INSERT OR IGNORE INTO policy_sources(key, name, apps, kind, licence, licence_class, url, status, reason, added_by, added)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, name, apps, kind, lic, cls, url, "approved" if ok else "blocked", why, "system", _now()))
            for key, name, apps, subj, lic, cls, url, note in RESEARCHED_SOURCES:
                ok = LICENCE_CLASSES[cls][0]
                cur = db.execute("""INSERT OR IGNORE INTO policy_sources(key, name, apps, kind, licence, licence_class, url, status, reason, added_by, added)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, name, apps, "researched: " + subj, lic, cls, url,
                                                                      "pending" if ok else "blocked", note, "research", _now()))
                if cur.rowcount and ok:                 # a recommendation for the admin; nothing is approved here
                    change = {"type": "source", "key": key, "status": "approved", "licence_class": cls}
                    db.execute("""INSERT OR IGNORE INTO recommendations(created, app, kind, title, rationale, evidence, change, fingerprint)
                                  VALUES(?,?,?,?,?,?,?,?)""", (_now(), None, "new source", "Approve a researched source for %s: %s" % (subj, name),
                                                               note, json.dumps({"licence": lic, "class": cls, "url": url}),
                                                               json.dumps(change), core.fingerprint("new source", "", json.dumps(change, sort_keys=True))))
            for day, words, status, keys in ADMIN_DECISIONS:
                for key in keys:
                    row = db.execute("SELECT status, licence_class, reason FROM policy_sources WHERE key = ? AND decided_by IS NULL", (key,)).fetchone()
                    if not row or row[0] != "pending":
                        continue
                    if status == "approved":
                        why = "Approved by the admin on %s (\u201c%s\u201d). Facts only: no wording from the source is stored. Conditions: %s" % (day, words, row[2])
                        db.execute("UPDATE policy_sources SET status = 'approved', reason = ?, decided_by = 'admin', decided_at = ? WHERE key = ?",
                                   (why, _now(), key))
                        db.execute("UPDATE recommendations SET status = 'applied', decided_by = 'admin', decided_at = ?, note = ? "
                                   "WHERE status = 'pending' AND kind = 'new source' AND change LIKE ?", (_now(), "approved on " + day, '%%"key": "%s"%%' % key))
                        self._version(db, "admin", {"source": key, "status": "approved", "licence_class": row[1], "was": ["pending", row[1]]}, why[:500])
                    elif key in HELD_REASON and HELD_REASON[key] not in (row[2] or ""):
                        db.execute("UPDATE policy_sources SET reason = ? WHERE key = ?", (HELD_REASON[key] + " — " + (row[2] or ""), key))
            for key, (val, desc) in DEFAULT_PARAMS.items():
                db.execute("INSERT OR IGNORE INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)",
                           (key, json.dumps(val), desc, _now(), "system"))
            for k, v in (budgets or {}).items():
                db.execute("INSERT OR IGNORE INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)",
                           ("budget.%s.%s" % (app_id, k), json.dumps(v), "%s: how much one turn harvests (%s)" % (app_id, k), _now(), "system"))

    # -- sources
    def source(self, key):
        return self.store.one("SELECT * FROM policy_sources WHERE key = ?", (key,))

    def sources(self):
        return self.store.query("SELECT * FROM policy_sources ORDER BY apps, key")

    def check(self, key):
        """(allowed?, licence class, reason) for one source key. Unknown keys are registered as pending/unknown."""
        if not key:
            return False, "unknown", "no source named"
        s = self.source(key)
        if s is None:
            with self.store.write() as db:
                db.execute("""INSERT OR IGNORE INTO policy_sources(key, name, apps, kind, licence, licence_class, status, reason, added_by, added)
                              VALUES(?,?,?,?,?,?,?,?,?,?)""", (key, key, self.c.app_id, "unregistered", "unknown", "unknown", "pending",
                                                              "seen in a harvest plan; licence not yet established", "engine", _now()))
            return False, "unknown", "source not in the registry (registered as pending)"
        if s["status"] != "approved":
            return False, s["licence_class"], "%s: %s" % (s["status"], s["reason"] or LICENCE_CLASSES.get(s["licence_class"], (0, ""))[1])
        return True, s["licence_class"], "approved: " + (s["reason"] or "")

    def set_source(self, key, status, actor, reason, db=None, licence_class=None):
        if status not in ("approved", "blocked", "pending"):
            raise core.UserError("status must be approved, blocked or pending")
        s = self.source(key)
        if not s:
            raise core.UserError("No such source.")
        cls = licence_class or s["licence_class"]
        if cls not in LICENCE_CLASSES:
            raise core.UserError("Unknown licence class.")

        def run(d):
            d.execute("UPDATE policy_sources SET status = ?, licence_class = ?, reason = ?, decided_by = ?, decided_at = ? WHERE key = ?",
                      (status, cls, reason, actor, _now(), key))
            self._version(d, actor, {"source": key, "status": status, "licence_class": cls, "was": [s["status"], s["licence_class"]]}, reason)
        if db is not None:
            run(db)
        else:
            with self.store.write() as d:
                run(d)

    def add_source(self, key, name, apps, kind, licence, licence_class, url, actor, reason):
        if licence_class not in LICENCE_CLASSES:
            raise core.UserError("Unknown licence class.")
        with self.store.write() as db:
            db.execute("""INSERT INTO policy_sources(key, name, apps, kind, licence, licence_class, url, status, reason, added_by, added)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, name, apps, kind, licence, licence_class, url, "pending", reason, actor, _now()))
            self._version(db, actor, {"source_added": key, "licence_class": licence_class}, reason)

    # -- parameters
    def param(self, key, default=None):
        v = self.store.scalar("SELECT value FROM policy_params WHERE key = ?", (key,))
        return json.loads(v) if v is not None else default

    def params(self):
        out = self.store.query("SELECT * FROM policy_params ORDER BY key")
        for r in out:
            r["value"] = json.loads(r["value"])
        return out

    def set_param(self, key, value, actor, reason, db=None):
        def run(d):
            old = d.execute("SELECT value FROM policy_params WHERE key = ?", (key,)).fetchone()
            d.execute("""INSERT INTO policy_params(key, value, description, updated, updated_by) VALUES(?,?,?,?,?)
                         ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated, updated_by = excluded.updated_by""",
                      (key, json.dumps(value), None, _now(), actor))
            self._version(d, actor, {"param": key, "value": value, "was": json.loads(old[0]) if old else None}, reason)
        if db is not None:
            run(db)
        else:
            with self.store.write() as d:
                run(d)

    def _version(self, db, actor, change, reason):
        db.execute("INSERT INTO policy_versions(at, actor, change, reason) VALUES(?,?,?,?)", (_now(), actor, json.dumps(change, ensure_ascii=False), reason))

    def version(self):
        return self.store.scalar("SELECT max(id) FROM policy_versions", default=0)

    def versions(self, limit=100):
        out = self.store.query("SELECT * FROM policy_versions ORDER BY id DESC LIMIT ?", (limit,))
        for r in out:
            r["change"] = json.loads(r["change"])
        return out


class HarvestLog:
    """Every harvest task, its source and why — hash-chained, archived monthly."""

    def __init__(self, commons):
        self.c = commons
        self.store = commons.store

    def write(self, db, app, action, title, source_key, licence_class, decision, reason, items=0, new=0, merged=0, seconds=0.0,
              budget_key=None, turn_id=None, policy_version=None):
        prev = db.execute("SELECT hash FROM harvest_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = prev[0] if prev else "0" * 64
        row = {"at": _now(), "app": app, "domain": DOMAIN_OF.get(app, app), "action": action, "title": (title or "")[:300],
               "source_key": source_key, "licence_class": licence_class, "decision": decision, "items": int(items), "new": int(new),
               "merged": int(merged), "seconds": round(float(seconds), 3), "reason": (reason or "")[:1000], "budget_key": budget_key,
               "turn_id": turn_id, "policy_version": policy_version}
        h = _hash(prev, row)
        cols = list(row) + ["prev_hash", "hash"]
        return db.execute("INSERT INTO harvest_log(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                          [row[k] for k in row] + [prev, h]).lastrowid

    def verify(self):
        prev, n = "0" * 64, 0
        for r in self.store.query("SELECT * FROM harvest_log ORDER BY id"):
            row = {k: r[k] for k in ("at", "app", "domain", "action", "title", "source_key", "licence_class", "decision", "items", "new",
                                     "merged", "seconds", "reason", "budget_key", "turn_id", "policy_version")}
            if r["prev_hash"] != prev or _hash(prev, row) != r["hash"]:
                return {"ok": False, "entries": n, "broken_at": r["id"]}
            prev, n = r["hash"], n + 1
        return {"ok": True, "entries": n, "last_hash": prev}

    def recent(self, app=None, decision=None, limit=200):
        where, args = [], []
        if app:
            where.append("app = ?"); args.append(app)
        if decision:
            where.append("decision = ?"); args.append(decision)
        sql = "SELECT * FROM harvest_log" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        return self.store.query(sql, args + [min(int(limit), 2000)])

    def archive(self):
        """Append the entries not yet archived to <commons>/archives/harvest-YYYY-MM.jsonl (one file per month)."""
        last = int(self.c.setting("archive:last_id", 0) or 0)
        rows = self.store.query("SELECT * FROM harvest_log WHERE id > ? ORDER BY id LIMIT 20000", (last,))
        if not rows:
            return {"archived": 0}
        folder = os.path.join(self.c.folder, "archives")
        os.makedirs(folder, exist_ok=True)
        by_month = {}
        for r in rows:
            by_month.setdefault(r["at"][:7], []).append(r)
        for month, rs in by_month.items():
            with open(os.path.join(folder, "harvest-%s.jsonl" % month), "a", encoding="utf-8") as f:
                for r in rs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        self.c.set_setting("archive:last_id", rows[-1]["id"])
        return {"archived": len(rows), "folder": folder}


class Approvals:
    """AI-recommended changes waiting for the admin, and the admin passphrase that decides them."""

    def __init__(self, commons, registry):
        self.c, self.reg, self.store = commons, registry, commons.store

    # -- admin passphrase (PBKDF2-SHA256)
    def admin_set(self):
        return bool(self.c.setting("admin:pass"))

    def set_admin(self, new, old=None):
        if len(new or "") < 8:
            raise core.UserError("Choose an admin passphrase of at least 8 characters.")
        if self.admin_set() and not self.check_admin(old):
            raise core.UserError("The current admin passphrase is not correct.")
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", new.encode("utf-8"), bytes.fromhex(salt), 200000).hex()
        self.c.set_setting("admin:pass", salt + "$" + h)
        with self.store.write() as db:
            self.reg._version(db, "admin", {"admin_passphrase": "set"}, "admin passphrase set or changed")
        return {"ok": True}

    def check_admin(self, passphrase):
        v = self.c.setting("admin:pass")
        if not v or not passphrase:
            return False
        salt, h = v.split("$", 1)
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), 200000).hex(), h)

    def _require(self, passphrase):
        if not self.admin_set():
            raise core.UserError("Set the admin passphrase first (Harvesting tab → Admin).")
        if not self.check_admin(passphrase):
            raise core.UserError("Admin passphrase not correct — nothing was changed.")

    # -- recommendations
    def recommend(self, db, app, kind, title, rationale, evidence, change):
        fp = core.fingerprint(kind, app or "", json.dumps(change, sort_keys=True))
        cur = db.execute("""INSERT OR IGNORE INTO recommendations(created, app, kind, title, rationale, evidence, change, fingerprint)
                            VALUES(?,?,?,?,?,?,?,?)""", (_now(), app, kind, title, rationale, json.dumps(evidence, default=str), json.dumps(change), fp))
        return cur.rowcount

    def list(self, status=None, limit=200):
        sql = "SELECT * FROM recommendations" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?"
        out = self.store.query(sql, ([status] if status else []) + [limit])
        for r in out:
            r["evidence"], r["change"] = json.loads(r["evidence"] or "null"), json.loads(r["change"])
        return out

    def decide(self, rid, approve, passphrase, note=""):
        self._require(passphrase)
        r = self.store.one("SELECT * FROM recommendations WHERE id = ?", (int(rid),))
        if not r:
            raise core.UserError("No such recommendation.")
        if r["status"] != "pending":
            raise core.UserError("Already decided (%s)." % r["status"])
        change = json.loads(r["change"])
        with self.store.write() as db:
            if approve:
                why = "approved recommendation #%d: %s" % (r["id"], r["title"])
                if change["type"] == "param":
                    self.reg.set_param(change["key"], change["value"], "admin", why, db)
                elif change["type"] == "source":
                    self.reg.set_source(change["key"], change["status"], "admin", why, db, change.get("licence_class"))
                status = "applied" if change["type"] in ("param", "source") else "acknowledged"
            else:
                status = "rejected"
            db.execute("UPDATE recommendations SET status = ?, decided_by = 'admin', decided_at = ?, note = ? WHERE id = ?",
                       (status, _now(), (note or "")[:500], r["id"]))
        return {"id": r["id"], "status": status}

    def admin_source(self, key, status, passphrase, reason, licence_class=None, accept_restriction=False):
        """The admin's own registry decision. Approving a restricted licence class needs an explicit acceptance."""
        self._require(passphrase)
        cls = licence_class or (self.reg.source(key) or {}).get("licence_class")
        if status == "approved" and cls in LICENCE_CLASSES and not LICENCE_CLASSES[cls][0] and not accept_restriction:
            raise core.UserError("This licence class (%s) puts restrictions on QueryBook: %s Tick the acceptance box to approve it anyway."
                                 % (cls, LICENCE_CLASSES[cls][1]))
        self.reg.set_source(key, status, "admin", reason or "admin decision", licence_class=licence_class)
        return {"ok": True}


def master_running(commons):
    """The master harvesting switch, shared by the three applications."""
    return commons.setting("harvest:master", "running") != "stopped"


class Engine:
    """Turn-taking across the three applications (alternating language, STEM and history)."""

    def __init__(self, commons, registry):
        self.c, self.reg, self.store = commons, registry, commons.store
        self.last_refusal = None        # why the last claim gave no turn: stopped, off, busy, other, paused

    def heartbeat(self, app, version=""):
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO app_heartbeat(app, at, version) VALUES(?,?,?)",
                       (app, datetime.datetime.now(datetime.timezone.utc).timestamp(), version))

    def _active(self, db, now):
        win = float(self.reg.param("rotation.active_window_s", 180))
        return [r[0] for r in db.execute("SELECT app FROM app_heartbeat WHERE at >= ? ORDER BY app", (now - win,))]

    def _app_state(self, db, app):
        """Recent productivity of an application: its last finished turns. A turn that found nothing new only because
        a site asked it to wait, a task failed or the turn was cut short is "held up", not "out of work": it earns a
        short pause, never the long idle back-off."""
        rows = db.execute("SELECT result, ended FROM engine_turns WHERE app = ? AND ended IS NOT NULL ORDER BY id DESC LIMIT 8", (app,)).fetchall()
        res = [json.loads(r[0] or "{}") for r in rows]
        empty = held = 0
        for r in res:                                      # consecutive turns that produced nothing new
            if r.get("new", 0) or r.get("checks_answered", 0):
                break
            if r.get("deferred") or r.get("failed") or r.get("error") or r.get("timeout") or r.get("abandoned"):
                held += 1
            else:
                empty += 1
        rate = [r.get("new", 0) / max(0.5, r.get("seconds", 1.0)) for r in res[:5]]
        last_end = rows[0][1] if rows else None
        return {"empty_streak": empty, "held_streak": held, "rate": sum(rate) / len(rate) if rate else None, "last_end": last_end}

    def claim(self, app):
        """Whose turn is it? Returns the new turn if it is `app`'s, else None. Atomic across processes."""
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        tmo = float(self.reg.param("rotation.turn_timeout_s", 900))
        stopped = not master_running(self.c)
        off = {a for a in DOMAIN_OF if self.c.setting("auto:%s" % a, "on") == "off"}
        win = float(self.reg.param("rotation.active_window_s", 180))
        with self.store.write() as db:
            db.execute("INSERT OR REPLACE INTO app_heartbeat(app, at, version) VALUES(?,?,?)", (app, now, ENGINE_VERSION))
            if stopped or app in off:
                self.last_refusal = "stopped" if stopped else "off"
                return None                                # the master switch, or this application's own switch, is off
            cur = db.execute("SELECT id, app, started FROM engine_turns WHERE ended IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if cur:
                started = _ts(cur[2])
                beat = db.execute("SELECT at FROM app_heartbeat WHERE app = ?", (cur[1],)).fetchone()
                gone = cur[1] != app and now - started > win and (not beat or now - beat[0] > win)
                if now - started < tmo and not gone:
                    self.last_refusal = "busy"
                    return None                            # someone is harvesting
                # the turn ran past its time, or its application stopped answering (closed mid-turn): give it up
                db.execute("UPDATE engine_turns SET ended = ?, result = ? WHERE id = ?",
                           (_now(), json.dumps({"abandoned": True} if gone else {"timeout": True}), cur[0]))
            active = [a for a in self._active(db, now) if a not in off]
            if app not in active:
                active.append(app)
            last = db.execute("SELECT app FROM engine_turns ORDER BY id DESC LIMIT 1").fetchone()
            last = last[0] if last else None
            w_check = float(self.reg.param("rotation.check_weight", 2.0))
            w_rep = float(self.reg.param("rotation.repeat_penalty", 5.0))
            back_max = float(self.reg.param("rotation.idle_backoff_max_s", 14400))
            w_back = float(self.reg.param("rotation.wait_backoff_max_s", 600))
            scores, why = {}, {}
            for a in sorted(active):
                st = self._app_state(db, a)
                checks = db.execute("SELECT count(*) FROM requests WHERE to_app = ? AND status = 'open'", (a,)).fetchone()[0]
                s, reasons = 1.0, []
                if st["rate"] is None:
                    s += 3.0; reasons.append("has not harvested yet")
                else:
                    s += min(3.0, st["rate"] / 50.0); reasons.append("recent rate %.1f new facts/s" % st["rate"])
                if checks:
                    s += w_check * min(5, checks) / 5.0 * 3; reasons.append("%d checks waiting for it" % checks)
                since = now - _ts(st["last_end"]) if st["last_end"] else 1e9
                if st["empty_streak"]:
                    pause = min(back_max, 60.0 * (4 ** (st["empty_streak"] - 1)))
                    if since < pause and not checks:
                        s = -1.0; reasons.append("paused %d s after %d turn(s) with nothing new (less volume)" % (pause, st["empty_streak"]))
                elif st["held_streak"]:
                    pause = min(w_back, 30.0 * st["held_streak"])
                    if since < pause and not checks:
                        s = -1.0; reasons.append("waiting %d s: its sources asked it to slow down or failed (%d turn(s)); not out of work"
                                                 % (pause, st["held_streak"]))
                if a == last and len(active) > 1:
                    s -= w_rep; reasons.append("had the last turn (alternate)")
                scores[a], why[a] = round(s, 2), reasons
            best = max(sorted(scores), key=lambda a: scores[a])
            if best != app or scores[best] < 0:
                self.last_refusal = "paused" if scores.get(app, -1) < 0 else "other"
                return None
            self.last_refusal = None
            reason = "%s's turn: %s" % (DOMAIN_OF[app], "; ".join(why[app]))
            tid = db.execute("INSERT INTO engine_turns(started, app, domain, reason, scores) VALUES(?,?,?,?,?)",
                             (_now(), app, DOMAIN_OF[app], reason, json.dumps({"scores": scores, "why": why}))).lastrowid
        return {"id": tid, "app": app, "reason": reason, "scores": scores}

    def manual(self, app, reason="started by hand"):
        with self.store.write() as db:
            tid = db.execute("INSERT INTO engine_turns(started, app, domain, reason, scores) VALUES(?,?,?,?,?)",
                             (_now(), app, DOMAIN_OF[app], reason, "{}")).lastrowid
        return {"id": tid, "app": app, "reason": reason}

    def finish(self, turn, result):
        with self.store.write() as db:
            db.execute("UPDATE engine_turns SET ended = ?, result = ? WHERE id = ?", (_now(), json.dumps(result, default=str), turn["id"]))

    def status(self):
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        hb = self.store.query("SELECT * FROM app_heartbeat ORDER BY app")
        for h in hb:
            h["seconds_ago"] = round(now - h["at"], 1)
        turns = self.store.query("SELECT * FROM engine_turns ORDER BY id DESC LIMIT 30")
        for t in turns:
            t["result"] = json.loads(t["result"] or "null")
            t["scores"] = json.loads(t["scores"] or "{}")
        return {"version": ENGINE_VERSION, "heartbeats": hb, "turns": turns}


def _ts(s):
    if not s:
        return 0.0
    return datetime.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc).timestamp()


class Learner:
    """Reads the harvest record and recommends changes (never applies them)."""

    MIN_RUNS = 3

    def __init__(self, commons, registry, approvals):
        self.c, self.reg, self.ap, self.store = commons, registry, approvals, commons.store

    def review(self, app):
        made = 0
        rows = self.store.query("""SELECT action, budget_key, decision, items, new, merged, seconds, source_key, licence_class FROM harvest_log
                                   WHERE app = ? ORDER BY id DESC LIMIT 300""", (app,))
        by = {}
        for r in rows:
            by.setdefault(r["action"], []).append(r)
        with self.store.write() as db:
            for action, rs in by.items():
                done = [r for r in rs if r["decision"] == "harvested"][:5]
                failed = [r for r in rs[:5] if r["decision"] == "failed"]
                key = next((r["budget_key"] for r in done if r["budget_key"]), None)
                pkey = "budget.%s.%s" % (app, key) if key else None
                cur = self.reg.param(pkey) if pkey else None
                if len(done) >= self.MIN_RUNS and isinstance(cur, (int, float)) and cur > 0:
                    items = sum(r["items"] for r in done)
                    new = sum(r["new"] for r in done)
                    secs = sum(r["seconds"] or 0 for r in done) / len(done)
                    share = new / items if items else 0.0
                    if share >= 0.9 and secs <= 10.0 and cur < 100000:
                        val = int(round(cur * 1.5))
                        made += self.ap.recommend(db, app, "speed", "Harvest more per turn: %s %s → %s" % (pkey, cur, val),
                                                  "The last %d '%s' tasks were %d%% new facts and took %.1f s each on average: larger batches "
                                                  "would finish the same work in fewer turns." % (len(done), action, round(100 * share), secs),
                                                  {"runs": len(done), "new_share": round(share, 3), "mean_seconds": round(secs, 2)},
                                                  {"type": "param", "key": pkey, "value": val})
                    elif items and share <= 0.1 and cur > 10:
                        val = max(10, int(cur // 2))
                        made += self.ap.recommend(db, app, "volume", "Harvest less per turn: %s %s → %s" % (pkey, cur, val),
                                                  "The last %d '%s' tasks were only %d%% new (the rest duplicates): smaller batches "
                                                  "spend less time and storage on facts already held." % (len(done), action, round(100 * share)),
                                                  {"runs": len(done), "new_share": round(share, 3)}, {"type": "param", "key": pkey, "value": val})
                if len(failed) >= 3:
                    made += self.ap.recommend(db, app, "reliability", "Pause the failing task '%s'" % action,
                                              "%d of its last 5 runs failed; pausing it stops wasted turns until the cause is fixed." % len(failed),
                                              {"failures": len(failed)}, {"type": "param", "key": "disabled.%s.%s" % (app, action), "value": True})
            # sources blocked only because nobody has classified their licence yet
            for s in self.store.query("SELECT key, name FROM policy_sources WHERE status = 'pending' AND licence_class = 'unknown'"):
                demand = sum(1 for r in rows if r["source_key"] == s["key"] and r["decision"] == "blocked")
                if demand:
                    made += self.ap.recommend(db, app, "source", "Classify the licence of '%s'" % s["name"],
                                              "Harvest plans asked for this source %d time(s) but its licence is unknown, so it is blocked. "
                                              "Establish the licence; approve only if its class is unrestricted." % demand,
                                              {"blocked_requests": demand}, {"type": "review", "key": s["key"]})
            # checks waiting too long between applications → give them more weight in the rotation
            waits = db.execute("""SELECT avg(strftime('%s', substr(answered, 1, 19)) - strftime('%s', substr(created, 1, 19)))
                                  FROM (SELECT created, answered FROM requests WHERE status = 'answered' ORDER BY id DESC LIMIT 50)""").fetchone()[0]
            tick = float(self.reg.param("schedule.tick_s", 30))
            if waits and waits > 20 * tick:
                cw = float(self.reg.param("rotation.check_weight", 2.0))
                made += self.ap.recommend(db, None, "speed", "Answer cross-checks sooner: rotation.check_weight %s → %s" % (cw, cw + 1),
                                          "Checks waited %.0f s on average before being answered; a higher weight gives the answering "
                                          "application its turn sooner." % waits, {"mean_wait_s": round(waits, 1)},
                                          {"type": "param", "key": "rotation.check_weight", "value": cw + 1})
        return made

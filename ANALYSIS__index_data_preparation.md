# Analysis: how `usep_gh_handler_app` prepares data sent to Solr

## Executive summary

This app prepares Solr index data using a **hybrid approach**, but the dominant mechanism is **XSLT transformation of inscription XML** rather than Python assembling a large Solr field dictionary.

In practice:

- The web app receives a GitHub webhook describing changed files.
- It updates a local checkout of the data repo.
- It copies XML and resources into the web-served data area.
- It normalizes inscription XML files by rewriting `xi:include` references.
- For each inscription that should be indexed, it loads the inscription XML and applies an XSLT stylesheet referenced by `usep_gh__SOLR_XSL_PATH`.
- The result of that XSLT is posted directly to Solr as **XML**.
- After that initial post, the app performs two additional **Python-driven follow-up updates** to Solr:
  - a bibliography enrichment step
  - a transcription enrichment step

So the answer to your question is:

- **The main Solr document is produced largely by stylesheet transformation of source XML.**
- **Python orchestrates the workflow, chooses which files to index, and performs some post-transform enrichment updates.**
- **There is not a live Python parser building the full Solr payload field-by-field.** An older parser module exists, but it is commented out and not used.

---

## Source-of-truth modules

The key files for understanding the live behavior are:

- `usep_gh_handler_app/usep_gh_handler.py`
- `usep_gh_handler_app/utils/web_app_helper.py`
- `usep_gh_handler_app/utils/processor.py`
- `usep_gh_handler_app/utils/indexer.py`
- `usep_gh_handler_app/utils/bib_adder.py`
- `usep_gh_handler_app/utils/transcription_adder.py`
- `usep_gh_handler_app/utils/reindex_all_support.py`

Helpful but **not source-of-truth for the current implementation**:

- `usep_gh_handler_app/README.md`
  - useful overview of queue flow
  - broadly accurate about the sequence of jobs
- `usep_gh_handler_app/utils/indexer_parser.py`
  - appears to be a historical Python field-extraction implementation
  - fully commented out
  - not referenced by the active code path

---

## High-level data-preparation architecture

## 1. Webhook receives changed file information

The Flask app entry point is `handle_github_push()` in `usep_gh_handler.py`.

Its responsibilities are mostly orchestration:

- log the request
- parse the GitHub payload
- determine `files_updated` and `files_removed`
- enqueue background processing

The relevant helper is `WebAppHelper.prep_data_dict()` in `utils/web_app_helper.py`.

That helper:

- parses the JSON webhook payload
- iterates over `commit_info['commits']`
- aggregates:
  - `added`
  - `modified`
  - `removed`
- produces a dict like:
  - `files_updated`
  - `files_removed`
  - `timestamp`

Important point: at this stage, the app is **not preparing Solr fields**. It is only determining **which source files may require reindexing**.

---

## 2. The app updates the local source tree and rebuilds the web-served XML set

The queue flow described in the README is basically correct and matches the code:

- `usep_gh_handler.handle_github_push()`
- `utils.processor.run_call_git_pull()`
- `utils.processor.run_copy_files()`
- `utils.processor.run_xinclude_updater()`
- `utils.indexer.run_update_index()`
- then per-file jobs:
  - `utils.indexer.run_update_entry()`
  - `utils.indexer.run_remove_entry()`

### `run_call_git_pull()`

In `utils/processor.py`:

- `Puller.call_git_pull()` runs `git pull` in `usep_gh__GIT_CLONED_DIR_PATH`.
- `Copier.get_files_to_update()` and `get_files_to_remove()` determine the lists that should ultimately be indexed or removed.

Again, still no Solr field preparation yet.

### `run_copy_files()`

`Copier.copy_files()` performs three copy phases:

- `_copy_resources()`
- `_build_unified_inscriptions()`
- `_copy_inscriptions()`

This is an important part of how Solr input is prepared.

### `_build_unified_inscriptions()`

This method merges inscription XML from three source directories in the cloned repo into a temporary unified area:

- `xml_inscriptions/bib_only/`
- `xml_inscriptions/metadata_only/`
- `xml_inscriptions/transcribed/`

using `rsync`.

This means the Solr indexer does **not** directly index from the repo’s original three-way split. Instead, Python first creates a **unified inscription set** in a staging area.

### `_copy_inscriptions()`

The unified temp set is then copied into:

- `usep_gh__WEBSERVED_DATA_DIR_PATH/inscriptions`

This web-served `inscriptions` directory becomes the canonical source used by the indexer.

### What this means conceptually

Before any Solr transform happens, Python performs a substantial **filesystem-level preparation step**:

- collecting data from multiple content-status directories
- flattening them into one working inscription corpus
- placing them in the location from which indexing will occur

So while Python is not building most Solr fields directly, it **does prepare the source dataset** that the XSLT will consume.

---

## 3. The app rewrites `xi:include` links before indexing

After copying, `run_xinclude_updater()` calls `XIncludeUpdater.update_xinclude_references()`.

This method iterates through every XML file in the web-served `inscriptions` directory and rewrites specific include URLs:

- `http://library.brown.edu/usep_data/resources/include_publicationStmt.xml`
- `http://library.brown.edu/usep_data/resources/include_taxonomies.xml`
- `http://library.brown.edu/usep_data/resources/titles.xml`

to local relative paths:

- `../resources/include_publicationStmt.xml`
- `../resources/include_taxonomies.xml`
- `../resources/titles.xml`

### Why this matters for Solr preparation

This is a key preprocessing step.

The inscription XML that is later transformed for Solr is **not used exactly as it arrives from the repo**. The app first modifies it so that include references match the deployed web-app filesystem layout.

That tells us:

- the XSLT and/or XML processing likely depends on those local resources being resolvable in the deployment context
- the app treats the copied inscription XML as a **derived working copy**, not a pristine mirror of the repo files

So the preparation pipeline is:

- GitHub repo XML
- copied and unified by Python
- include paths rewritten by Python
- then transformed for Solr

---

## 4. Only selected paths trigger indexing

`utils/indexer.py` contains `Indexer.worthwhile_dirs`:

- `bib_only`
- `metadata_only`
- `transcribed`

The `check_updated_file_path()` and `check_removed_file_path()` methods simply test whether a changed path contains one of those substrings.

### Implication

The app does not attempt to rebuild Solr for every changed file in the repo.

Instead, the webhook-driven index update is limited to files under those inscription-content directories.

This filtering is important because it means:

- some resource changes may affect indexing indirectly, but the incremental webhook logic is file-path based
- a full `/reindex_all/` is the safer path when resource-level changes, XSLT changes, or shared include changes need to be reflected comprehensively

---

## 5. The main Solr document is built by XSLT, not by Python assembling fields

This is the central answer.

In `utils/indexer.py`, `Indexer.update_index_entry()` does the real indexing work:

1. build the full inscription file path from `WEBSERVED_DATA_DIR_PATH/inscriptions/<filename>`
2. call `_build_solr_doc()`
3. post the result to Solr with `_post_solr_update()`
4. run follow-up enrichment:
   - `_update_bib()`
   - `_update_transcription()`

### `_build_solr_doc()`

This method is the clearest statement of the architecture.

It:

- opens the inscription XML file
- opens the XSL file located at `usep_gh__SOLR_XSL_PATH`
- parses both with `lxml.etree`
- builds an `etree.XSLT` transformer
- applies the XSLT to the XML DOM
- serializes the transformed result as text
- returns that text

That text is then posted to Solr as `application/xml`.

### Interpretation

The **primary Solr payload is authored by the XSL stylesheet**, not by Python code extracting individual XML values and creating a dict or JSON document.

Python’s role here is:

- locate the XML
- locate the XSLT
- invoke the transformation
- send the transformed result to Solr

This is much closer to the “stylesheet transformation” pattern you mentioned than to the “Python builds the fields” pattern.

---

## 6. Where the main field definitions probably live

The code does not include the stylesheet itself inside `usep_gh_handler_app`, but the environment reference reveals the expected production path:

- `usep_gh__SOLR_XSL_PATH="/var/www/html/usep_data/resources/xsl/USEp_to_Solr.xsl"`

This strongly implies that the mapping from inscription TEI/XML to Solr fields is defined externally in:

- `USEp_to_Solr.xsl`

So if you want the authoritative definition of:

- which fields are created
- which XML nodes feed those fields
- whether fields are multi-valued
- how normalization is done
- how missing values are handled

then the most important artifact is **that XSL file**, not the Python in this repo.

Within this web app, Python is mostly the execution harness for that transform.

---

## 7. The initial Solr update is XML-over-HTTP

`Indexer._post_solr_update()` posts to:

- `SOLR_URL + "/update"`

with:

- request body = transformed XML
- content type = `application/xml`

This shows the first indexing step is a classic Solr XML update request.

### What that implies about document shape

The XSLT is almost certainly generating one of the standard Solr XML update formats, such as an `<add>` payload containing a `<doc>` with `<field>` children.

The unit test in `tests/test_indexer.py` confirms this expectation. It checks that `_build_solr_doc()` returns XML containing fragments like:

- `<field name="title">...`
- `<field name="msid_settlement">...`
- `<field name="msid_institution">...`
- `<field name="msid_repository">...`
- `<field name="msid_idno">...`
- `<field name="language">...`

So, even without seeing `USEp_to_Solr.xsl`, the test confirms that the XSLT produces literal Solr `<field>` elements.

### Bottom line

The initial document sent to Solr is:

- generated from XML by XSLT
- serialized as Solr update XML
- posted directly by Python

---

## 8. Python then performs a bibliography enrichment update

After the main XML/XSLT-driven post, `Indexer._update_bib()` runs.

This step is meaningfully different from the first one because here Python does perform logic that modifies data already in Solr.

### How `_update_bib()` works

- It derives `inscription_id` from the filename by stripping `.xml`.
- It creates `BibAdder(self.SOLR_URL, self.TITLES_URL)`.
- It calls `bibber.addBibl(inscription_id)`.

### `BibAdder.__init__()`

This fetches the titles XML from `usep_gh__TITLES_URL` and parses it with lxml.

So the bibliography enrichment depends on an external XML resource, not just the inscription XML.

### `BibAdder.addBibl()`

This method:

1. queries Solr for the just-indexed document:
   - query: `id:"<inscription_id>"`
   - fields requested: `bib_ids`
2. extracts the current `bib_ids` from the indexed Solr doc
3. for each `bib_id`, runs an XPath against `titles.xml` to collect ancestor bibliography IDs:
   - `//tei:bibl[@xml:id='<id>']/ancestor::tei:bibl/@xml:id`
4. creates a set of additional IDs
5. posts a JSON partial update back to Solr:
   - `[{"id": inscription_id, "bib_ids": {"add": [...]}}]`
6. triggers a soft commit

### Interpretation

This means the XSLT-generated initial doc is **not the complete final document**.

Instead:

- the initial transform provides at least a base `bib_ids` field
- Python then expands that field using `titles.xml` hierarchy
- the final indexed `bib_ids` is therefore a combination of:
  - initial transform output
  - Python post-processing using external XML hierarchy data

### Important nuance

This bibliography step is still driven by XML resources, but unlike the main transform:

- it is **not** done by XSLT inside the primary transform pipeline
- it is done by **Python + XPath + Solr JSON partial update**

So the app uses both styles:

- **XSLT for the base Solr document**
- **Python/XML/XPath for bibliography enrichment**

---

## 9. Python also performs a transcription enrichment update

After `_update_bib()`, `Indexer._update_transcription()` runs.

The intent is clear: add or update a `transcription` field in Solr.

### Important code-level observation

There appears to be a mismatch in the active code:

- `Indexer._update_transcription()` calls:
  - `transcriptor.add_transcription(inscription_id)`
- but `TranscriptionAdder.add_transcription()` is defined as:
  - `add_transcription(self, inscription_id, xml_path)`

and internally calls `self.index_value(xml_path)`.

So based on the code as written, the method call is missing the required `xml_path` argument.

Because `_update_transcription()` wraps its body in `try/except`, failures here would be logged and suppressed rather than aborting the whole indexing operation.

### Intended transcription-preparation logic

Even with that mismatch, the intended design is still visible in `utils/transcription_adder.py`.

The transcription update path would be:

1. open the inscription XML file
2. extract `//tei:div[@type='edition']/tei:ab`
3. serialize those elements
4. strip and normalize line content
5. collapse whitespace following `<lb/>` using regex
6. concatenate the resulting markup into a munged XML fragment
7. parse that munged fragment as XML
8. apply another XSLT transform loaded from `usep_gh__TRANSCRIPTION_PARSER_XSL_PATH`
9. convert the transform result to a string
10. send a Solr JSON update:
    - set `transcription` on the document identified by `id`

### This means transcription prep is another hybrid

The transcription field is not taken straight from the main `USEp_to_Solr.xsl` transform. Instead, it has its own specialized preparation flow:

- Python extracts and normalizes the relevant XML segment
- a second XSLT transforms that fragment into the indexed transcription value
- Python sends the result as a JSON partial update to Solr

So compared with the main document generation, transcription handling is more mixed:

- **Python does the extraction and munging**
- **XSLT does the conversion to the final indexed value**
- **Python posts the final partial update**

---

## 10. Reindex-all follows the same preparation model

The admin route `/reindex_all/` triggers `utils.reindex_all_support.run_call_simple_git_pull()`.

That path:

- performs `git pull`
- copies files into the unified web-served area
- enumerates all inscription XML files in `WEBSERVED_DATA_DIR_PATH/inscriptions/`
- fetches all Solr IDs
- computes orphaned Solr IDs
- enqueues:
  - `run_update_entry` for every inscription file
  - `run_remove_entry_via_id` for orphaned Solr docs

### Key takeaway

A full reindex does **not** use a different field-preparation algorithm.

It uses the same data-preparation approach:

- unified copied XML as input
- XInclude-rewritten working files
- XSLT-generated base Solr XML
- follow-up bibliography/transcription partial updates

The only difference is how the candidate files are selected.

---

## 11. What the old `indexer_parser.py` tells us

`utils/indexer_parser.py` is large and contains many methods that clearly represent an older design where Python parsed individual values directly from XML, such as:

- title
- language
- material
- msIdentifier pieces
- bibliography values
- status
- text genre
- object type
- etc.

But in the current file, this code is commented out from top to bottom and is not referenced by the active modules.

### Why this matters

This strongly suggests the project likely evolved from a more Python-centric extraction approach toward an XSLT-centric approach.

So if you have experience with projects where Python created Solr fields directly, this repo seems to contain evidence of that older model, but **the live implementation no longer works that way for the main document**.

The current source-of-truth behavior is the XSLT-based approach in `Indexer._build_solr_doc()`.

---

## 12. What is prepared in Python vs. what is prepared in XSLT

A useful way to think about this app is to separate responsibilities.

### Prepared in Python

Python is responsible for:

- parsing webhook commit payloads
- deciding which files are candidates for update/remove
- updating the local data checkout
- merging the three inscription source directories into one working corpus
- copying resources and inscriptions into the web-served area
- rewriting `xi:include` references to match deployment layout
- invoking the main XSLT transform
- posting transformed XML to Solr
- enriching bibliography fields from `titles.xml` using XPath
- preparing and posting a transcription partial update
- removing orphaned or deleted Solr records

### Prepared in XSLT

XSLT is responsible for:

- turning an inscription XML document into the main Solr XML update payload
- producing the base set of Solr `<field>` elements
- producing at least the fields observed in tests, such as:
  - `title`
  - `msid_settlement`
  - `msid_institution`
  - `msid_repository`
  - `msid_idno`
  - `language`
- transforming transcription XML fragments into the indexed transcription value via the second stylesheet

### Prepared partly in both

Some final Solr state is hybrid:

- `bib_ids`
  - likely initially present from the main XSLT transform
  - later expanded by Python using `titles.xml` hierarchy
- `transcription`
  - intended to be produced through Python extraction + XSLT fragment transform + Python Solr update

---

## 13. The actual Solr input is based on a derived working copy of the XML

This is an important architectural point.

The XML sent through the main Solr transform is not simply “whatever changed in GitHub.”

It is a **prepared deployment-local working copy** that has already been:

- pulled from the Git clone
- merged from multiple source directories
- copied into the web-served location
- edited so `xi:include` links point to local relative resources

That means if you are trying to understand “what data is sent to Solr,” you should think in terms of:

- **final local inscription XML in `WEBSERVED_DATA_DIR_PATH/inscriptions/`**

rather than:

- raw source file paths from the repo webhook payload

This distinction matters because the indexing transform operates on the local prepared file.

---

## 14. Important operational dependencies

The indexing behavior depends heavily on environment-configured paths and URLs.

Most important are:

- `usep_gh__WEBSERVED_DATA_DIR_PATH`
  - where the canonical working inscription files live
- `usep_gh__SOLR_URL`
  - Solr endpoint
- `usep_gh__SOLR_XSL_PATH`
  - path to the main XSLT used to generate the Solr XML update request
- `usep_gh__TITLES_URL`
  - titles XML used for bibliography hierarchy enrichment
- `usep_gh__TRANSCRIPTION_PARSER_XSL_PATH`
  - second XSLT for the transcription field
- `usep_gh__GIT_CLONED_DIR_PATH`
  - source repo checkout
- `usep_gh__TEMP_DATA_DIR_PATH`
  - staging area for unified inscriptions

Because the two XSL paths and the titles XML are external to this app directory, the complete field-level behavior cannot be fully reconstructed from `usep_gh_handler_app` alone.

This repo tells you **how the web app prepares and submits data**, but the exact shape of the base Solr document depends on the external stylesheet contents.

---

## 15. Practical answer to your original comparison

You described two common patterns:

- Python prepares Solr fields directly
- stylesheet transformations prepare Solr fields from XML

This app is mostly the second pattern.

### More precisely

- **Main Solr document:** stylesheet-driven
  - inscription XML is transformed by `USEp_to_Solr.xsl`
  - result is posted as Solr XML
- **Workflow and source preparation:** Python-driven
  - file selection, copying, unification, include rewriting
- **Post-index enrichment:** Python-driven with XML/XPath and an auxiliary XSLT
  - bibliography hierarchy expansion
  - transcription update

So if you had to summarize the architecture in one sentence:

> `usep_gh_handler_app` prepares Solr data by first constructing a deployment-local working corpus of inscription XML, then using XSLT to generate the primary Solr update document, and finally applying Python-driven partial updates for bibliography and transcription enrichment.

---

## 16. Caveats and notable issues in the current code

### `README.md` is overview-level only

The README accurately captures the queue sequence, but not the deeper details of how Solr data is generated. The code is indeed the better source-of-truth.

### `indexer_parser.py` is historical, not active

It may be tempting to read that as the field-preparation logic, but it does not represent the current implementation.

### Possible transcription bug

The call signature mismatch between:

- `Indexer._update_transcription()`
- `TranscriptionAdder.add_transcription()`

suggests that transcription enrichment may currently fail unless there is some unshown compatibility layer or older runtime behavior masking it. Based only on the code in this app, the intended flow is clear, but the active call looks incorrect.

### XSLT files are outside this repo folder

The most authoritative definition of the base Solr field mapping appears to live outside this app in the web-served resources area:

- `/var/www/html/usep_data/resources/xsl/USEp_to_Solr.xsl`
- `/var/www/html/usep_data/resources/xsl/transcription_index_val.xsl`

So this analysis can explain **how** data is prepared and sent, but not enumerate every field with certainty unless those stylesheets are also reviewed.

---

## Final conclusion

Within `usep_gh_handler_app`, the live Solr-preparation process works like this:

1. Python receives GitHub push metadata and identifies changed inscription files.
2. Python updates and reconstructs a local working set of inscription XML.
3. Python rewrites include references inside that working XML corpus.
4. Python loads each prepared inscription XML file.
5. Python applies an external XSLT stylesheet to generate the main Solr XML update payload.
6. Python posts that XSLT output directly to Solr.
7. Python then enriches the indexed document with additional partial updates:
   - expanded bibliography IDs via `titles.xml`
   - intended transcription text/value via a second XSLT-assisted process

So the webapp’s main indexing model is **XSLT-centric**, with Python serving as the orchestrator and enrichment layer rather than the primary field-construction engine.

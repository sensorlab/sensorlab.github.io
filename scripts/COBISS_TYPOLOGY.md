# COBISS/SICRIS typology codes

`scripts/cobiss_parser.py` reads a `code` attribute off the `<Typology>` element in each
COBISS bibliography entry (see `get_cobiss_data()`) and stores it verbatim in the `code`
field of `data/publications.json` / `data/cobiss.debug.json`. The raw COBISS XML actually
carries a human-readable label as the element's text content
(e.g. `<Typology code="1.01">Original scientific article</Typology>`), but the parser
currently discards that text and only keeps the code.

This table was built by fetching live bibliographies for several SensorLab researchers
and reading the `<Typology>` text directly out of the XML, so it reflects COBISS's own
labels rather than a guess.

Codes in **bold** are the ones actually surfaced on the public site (see
[What's shown on the public site](#whats-shown-on-the-public-site) below).

| Code | Typology |
|------|----------|
| **1.01** | Original scientific article |
| **1.02** | Review article |
| **1.03** | Other scientific articles |
| 1.04 | Professional article |
| 1.05 | Popular article |
| 1.06 | Published scientific conference contribution (invited lecture) |
| **1.08** | Published scientific conference contribution |
| 1.09 | Published professional conference contribution |
| 1.10 | Published scientific conference contribution abstract (invited lecture) |
| 1.11 | *not observed in sampled data* |
| 1.12 | Published scientific conference contribution abstract |
| 1.13 | Published professional conference contribution abstract |
| **1.16** | Independent scientific component part or a chapter in a monograph |
| 1.20 | Preface, editorial, afterword |
| 1.22 | *not observed in sampled data* |
| 1.25 | Other component parts |
| **2.01** | Scientific monograph |
| 2.05 | Other educational material |
| 2.06 | Dictionary, encyclopaedia, lexicon, manual, atlas, map |
| 2.08 | Doctoral dissertation |
| 2.09 | Master's thesis |
| 2.11 | Undergraduate thesis |
| 2.12 | Final research report |
| 2.13 | Treatise, preliminary study, study |
| 2.14 | Project documentation (preliminary design, working design) |
| **2.20** | Research data |
| 2.21 | Software |
| 2.23 | Patent application |
| **2.24** | Patent |
| 2.25 | Other monographs and other completed works |
| 2.30 | Proceedings of professional or unreviewed scientific conference contributions |
| 2.31 | Proceedings of peer-reviewed scientific conference contributions (international and foreign conferences) |
| 2.32 | Proceedings of peer-reviewed scientific conference contributions (domestic conferences) |
| 3.14 | Invited lecture at foreign university |
| 3.15 | Unpublished conference contribution |
| 3.16 | Unpublished invited conference lecture |
| 3.25 | Other performed works |
| **`preprint`** | Not a COBISS code &mdash; assigned internally by `cobiss_parser.py`'s `get_arxiv_data()` to entries sourced only from arXiv. |

`1.11` and `1.22` appear in `data/publications.json` but did not turn up in any of the
sampled researcher bibliographies used to build this table, so no confirmed label is
available yet. If you need them, fetch a fuller bibliography and look at the raw
`<Typology>` text, or extend `get_cobiss_data()` to capture `elem.find("Typology").text`
directly (see below).

## What's shown on the public site

The site deliberately only surfaces a subset of these typologies &mdash; this is an
intentional editorial choice, not a bug or an incomplete mapping:

- `layouts/publications/list.html` groups codes `1.01`/`1.02`/`1.03` as "Journals",
  `1.08` as "Conferences", `2.01` as "Books", `1.16` as "Book chapters", `2.24` as
  "Patents", and `preprint` as "Preprints".
- `layouts/people/single.html` uses a narrower grouping: `2.01` ("Books"), `1.16`
  ("Book Chapters"), `2.24` ("Patents"), and `1.01`/`1.02`/`1.03`/`1.08`/`preprint`
  lumped together as "Publications".

Every other code (theses, research reports, software, unpublished talks, popular
articles, etc.) is fetched and flagged by `is_sensorlab` in the pipeline, but is not
rendered on these public pages by design.

## Capturing the label directly from source

Since COBISS's XML already includes the readable label, `get_cobiss_data()` could store
it instead of (or alongside) the bare code, e.g.:

```python
entry["typology"] = _element_text(elem, "Typology")
```

That would make this table self-maintaining from the data instead of a document that
has to be kept in sync by hand.

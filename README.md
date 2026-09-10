# Taxonomizing ~17k responses to Jacob Coxon's viral tweet on quitting Anthropic

A taxonomy of the public reaction to
[the 2026-09-09 resignation thread](https://x.com/hilbertspaess/status/2097476196791709843),
from four broad moves down to individual tweets. The page is served from this
repo via GitHub Pages: **index.html**.

## What is here

- `index.html`: the post. Four moves, ten categories, 48 response types, each
  opening to its definition and three example posts with translations.
- `figures/`: the category bar chart used on the page, and the full two-ring donut of all 48 types (SVG + PNG).
- `taxonomy.json`: the induced coding scheme with definitions and two example
  snippets per type.
- `taxonomy_counts.json`: post counts per category, type, and venue.
- `pipeline/`: the code that produced everything, in run order:
  `fetch_conversation.py` (X API v2 download), `merge.py`, `classify.py`
  (stance labels), `taxonomy.py` (induce, assign, report),
  `make_taxonomy_figure.py`, `build_blogpost_html.py`.

## What is not here

The post-level data (every reply and quote as returned by the X API, and the
per-post labels) is kept privately and is not distributed with this repo. The
page quotes 144 individual public posts, linked to their originals.

## Method

X exposed 5,034 of 12,897 reported replies and 14,147 quote tweets. Spam was
removed, leaving 17,541 posts. Claude Opus 5 induced the taxonomy from a
1,300-post sample stratified by venue with the most-liked posts oversampled,
then assigned every post to one type through the Batches API. One labelling
pass, spot-checked, no human validation set. Reply coverage is the visible
thread only; hidden replies are likely more hostile than what is shown.

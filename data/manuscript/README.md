# Frozen manuscript inputs

This directory contains the immutable public-data snapshot used for the
manuscript analysis. It contains aggregate CDC surveillance extracts and U.S.
Census population/geometry inputs only; it contains no patient-level, private,
reviewer, or manuscript material.

`input_manifest.json` records the source, query scope, byte size, and SHA-256
digest for every file. Run `make frozen-data` to verify all five files before
they are copied to the ignored `data/raw/` runtime cache. `make reproduce` does
this automatically.

The tracked snapshot is the source of truth for manuscript reproduction. Use
`make live-reproduce` only to evaluate the same code against the current mutable
CDC view; live values may differ from the publication results.

These independently sourced U.S. government datasets retain their source terms;
the repository's MIT license applies to the analysis code. Source links and
transformations are recorded in the manifest.

## Census/TIGER/Line® notice

The geographic boundaries in this snapshot are provided for statistical data
collection and tabulation. They are not legal land descriptions and do not
determine jurisdictional authority, ownership, or entitlement. The U.S.
Government and Census Bureau make no warranty regarding positional or attribute
accuracy and assume no liability for the data.

The name TIGER/Line® may not be used as, or within, the proprietary name of a
commercial product; it may be used only to describe the nature of a product.

Source: U.S. Census Bureau, 2022 TIGER/Line® Shapefiles. See the
[2022 technical documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2022/TGRSHP2022_TechDoc_Ch1.pdf).

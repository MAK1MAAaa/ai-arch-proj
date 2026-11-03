# UNESCO source location records

`world_locations.json` derives from the [UNESCO DataHub World Heritage List](https://data.unesco.org/explore/dataset/whc001/), copyright UNESCO, under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). It uses the same fixed 2026-11-02 snapshot as the existing world catalogue. Original source hashes, attribution and transformations are retained in `world_locations_manifest.json`.

Processing selects the cultural and mixed records, maps them to existing site identities, and retains every original geometry coordinate in source order. Original component labels and references are included only after checking that their coordinates and order match the geometry. Repeated labels, references and coordinates are retained; zero-based source indices distinguish the records. No photographs or other media are redistributed.

The location sequence is separate from canonical representative points. Empty source sequences remain empty, including where the project has an independently sourced Wikidata representative. Display deduplication does not remove the original records or create new site identities. Source labels and points do not establish excavation accuracy, independently reviewed chronology or political attribution. This processing does not imply UNESCO endorsement.

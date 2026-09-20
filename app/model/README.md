# Mongo Collection Schemas

This package documents the MongoDB document shape used by the app.

| Collection | Schema |
| --- | --- |
| `Notices` | `model.notices.NoticeDocument` |
| `Jobs` | `model.jobs.JobDocument` |
| `PlacementOffers` | `model.placement_offers.PlacementOfferDocument` |
| `Users` | `model.users.UserDocument` |
| `Policies` | `model.policies.PolicyDocument` |
| `OfficialPlacementData` | `model.official_placement.OfficialPlacementDataDocument` |
| `PlacementYears` | `model.placement_years.PlacementYearDocument` |

The models allow extra fields to keep old Mongo documents readable while the canonical structured fields are documented here.

"""Tests for the current JIIT official placement page parser."""

import json

from model.official_placement import OfficialPlacementDataDocument
from services.official_placement import OfficialPlacementService, TARGET_URL


def _next_script(fragment: str) -> str:
    """Wrap a decoded fragment in the format emitted by Next.js."""
    return f"<script>self.__next_f.push({json.dumps([1, fragment])})</script>"


def test_target_url_points_to_students_placement_page() -> None:
    """Use the placement page rather than the site homepage."""
    assert TARGET_URL.endswith(
        "/existing-student/training-and-placement/students-placement"
    )


def test_parse_rendered_highlight_cards() -> None:
    """Parse the hydrated card markup visible in a browser."""
    html = """
    <div class="placement-sec student-placement-pg column-1 section-padding">
      <div class="mainheading__large">
        Placement Highlights – Graduating Batch 2026
      </div>
      <div class="highlights inner-page items grid">
        <div class="item">
          <div class="title">474</div>
          <div class="desc">Quality Companies Visited So Far</div>
        </div>
        <div class="item">
          <div class="title">Rs. 94.25 Lacs</div>
          <div class="desc">Highest Package by LinkedIn (2 Offers)</div>
        </div>
      </div>
    </div>
    """

    result = OfficialPlacementService().parse_all_batches_data(html)

    assert result is not None
    assert len(result.batches) == 1
    assert result.batches[0].batch_name == "2026"
    assert result.batches[0].is_active is True
    assert [item.title for item in result.batches[0].highlights] == [
        "474",
        "Rs. 94.25 Lacs",
    ]


def test_parse_next_payload_and_validate_database_document() -> None:
    """Parse the flight payload returned to requests before browser hydration."""
    highlights = {
        "__component": "jiit-youth-club.placement-highlights",
        "title": "Placement Highlights – Graduating Batch 2026",
        "list": [
            {
                "title": "Rs. 11.15 Lacs",
                "description": "Average Package",
            },
            {
                "title": "Rs. 7.01 Lacs",
                "description": "Median Package",
            },
        ],
    }
    recruiters = {
        "slidecount": 1,
        "Images": [
            {"image": "/uploads/acme.webp", "name": "Acme"},
        ],
    }
    html = _next_script(f'5:["$",{{"data":{json.dumps(highlights)}}}]')
    html += _next_script(f'23:["$",{json.dumps(recruiters)}]')

    result = OfficialPlacementService().parse_all_batches_data(html)

    assert result is not None
    assert result.batches[0].batch_name == "2026"
    assert result.batches[0].highlights[0].description == "Average Package"
    assert result.recruiter_logos[0].src == (
        "https://www.jiit.ac.in/uploads/acme.webp"
    )
    assert result.recruiter_logos[0].alt == "Acme"
    OfficialPlacementDataDocument(**result.model_dump())

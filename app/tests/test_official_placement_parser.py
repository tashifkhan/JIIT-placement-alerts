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


def test_parse_live_highlight_card_markup() -> None:
    """Parse the students-placement markup JIIT currently ships.

    The wrapper class is misspelled `palcement-sec`, and both 2027 and 2026
    highlight grids are in the initial HTML.
    """
    html = """
    <div class="inner-banner">
      <div class="mainheading__large">Training &amp; Placement</div>
      <h1>Students Placement</h1>
    </div>
    <div class="vector-bg-sec desc-sec">
      <div class="left">
        <p>Training and Placement activities are executed centrally from JIIT Noida.</p>
      </div>
    </div>
    <div class="palcement-sec student-placement-pg colum-1 section-padding">
      <div class="mainheading__large">
        Placement Highlights – Graduating Batch 2027
      </div>
      <div class="highlights inner-page items grid">
        <div class="item">
          <div class="title ">81</div>
          <div class="desc">Quality Companies Visited So Far</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 46.38 Lacs</div>
          <div class="desc">Highest Package by Amazon (3 Offers)</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 14.24 Lacs</div>
          <div class="desc">Average Package</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 11.00 Lacs</div>
          <div class="desc">Median Package</div>
        </div>
      </div>
    </div>
    <div class="palcement-sec student-placement-pg colum-2 section-padding">
      <div class="mainheading__large">
        Placement Highlights – Graduating Batch 2026
      </div>
      <div class="highlights inner-page items grid">
        <div class="item">
          <div class="title ">494</div>
          <div class="desc">Quality Companies Visited So Far</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 94.25 Lacs</div>
          <div class="desc">Highest Package by LinkedIn (2 Offers)</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 11.75 Lacs</div>
          <div class="desc">Average Package</div>
        </div>
        <div class="item">
          <div class="title ">Rs. 7.01 Lacs</div>
          <div class="desc">Median Package</div>
        </div>
      </div>
    </div>
    <section class="student-training-page">
      <div class="mainheading__large">Key Recruiters JIIT Noida : 2020-26</div>
      <div class="placements-items grid">
        <div class="item">
          <img alt="" src="/uploads/amazon.webp" />
        </div>
      </div>
    </section>
    """

    result = OfficialPlacementService().parse_all_batches_data(html)

    assert result is not None
    assert result.main_heading == "Training & Placement"
    assert result.intro_text is not None
    assert "Training and Placement activities" in result.intro_text
    assert [batch.batch_name for batch in result.batches] == ["2027", "2026"]
    assert result.batches[0].is_active is True
    assert result.batches[1].is_active is False
    assert [item.title for item in result.batches[0].highlights] == [
        "81",
        "Rs. 46.38 Lacs",
        "Rs. 14.24 Lacs",
        "Rs. 11.00 Lacs",
    ]
    assert result.batches[1].highlights[0].title == "494"
    assert result.recruiter_logos[0].src == (
        "https://www.jiit.ac.in/uploads/amazon.webp"
    )


def test_parse_correctly_spelled_placement_sec() -> None:
    """Keep the correctly spelled wrapper class working too."""
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


def test_parse_highlights_from_heading_when_wrapper_class_changes() -> None:
    """Fall back to Placement Highlights headings if section classes move."""
    html = """
    <section>
      <div class="mainheading__large">
        Placement Highlights – Graduating Batch 2027
      </div>
      <div class="highlights inner-page items grid">
        <div class="item">
          <div class="title">81</div>
          <div class="desc">Quality Companies Visited So Far</div>
        </div>
      </div>
    </section>
    """

    result = OfficialPlacementService().parse_all_batches_data(html)

    assert result is not None
    assert result.batches[0].batch_name == "2027"
    assert result.batches[0].highlights[0].title == "81"


def test_payload_logos_keep_company_names_over_empty_dom_alts() -> None:
    """Rendered recruiter images have empty alts; the flight payload has names."""
    recruiters = {
        "slidecount": 1,
        "Images": [
            {"image": "/uploads/amazon.webp", "name": "Amazon"},
        ],
    }
    html = """
    <div class="student-placement-pg">
      <div class="mainheading__large">
        Placement Highlights – Graduating Batch 2027
      </div>
      <div class="highlights">
        <div class="item">
          <div class="title">81</div>
          <div class="desc">Quality Companies Visited So Far</div>
        </div>
      </div>
    </div>
    <div class="placements-items">
      <img alt="" src="/uploads/amazon.webp" />
    </div>
    """
    html += _next_script(f'23:["$",{json.dumps(recruiters)}]')

    result = OfficialPlacementService().parse_all_batches_data(html)

    assert result is not None
    assert result.recruiter_logos[0].alt == "Amazon"


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

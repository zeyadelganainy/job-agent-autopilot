from jobagent.generate import _sort_projects_recent_first


def test_sort_projects_recent_first():
    data = {"projects": [
        {"name": "Old", "dates": "Jan 2021 – Mar 2021"},
        {"name": "New", "dates": "2024"},
        {"name": "Mid", "dates": "Jun 2022 – Dec 2023"},
        {"name": "Undated", "dates": ""},
    ]}
    _sort_projects_recent_first(data)
    assert [p["name"] for p in data["projects"]] == ["New", "Mid", "Old", "Undated"]


def test_sort_projects_handles_missing():
    data = {}                       # no projects key
    _sort_projects_recent_first(data)
    assert "projects" not in data

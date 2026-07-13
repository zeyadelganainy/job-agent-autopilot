from jobagent.generate import _sort_entries_recent_first


def test_sort_projects_recent_first():
    data = {"projects": [
        {"name": "Old", "dates": "Jan 2021 – Mar 2021"},
        {"name": "New", "dates": "2024"},
        {"name": "Mid", "dates": "Jun 2022 – Dec 2023"},
        {"name": "Undated", "dates": ""},
    ]}
    _sort_entries_recent_first(data)
    assert [p["name"] for p in data["projects"]] == ["New", "Mid", "Old", "Undated"]


def test_sort_experience_and_education_recent_first():
    data = {
        "experience": [
            {"role": "Old", "dates": "2019 – 2020"},
            {"role": "Current", "dates": "Aug 2023 – Present"},
            {"role": "Mid", "dates": "2021 – 2022"},
        ],
        "education": [
            {"school": "Diploma", "dates": "2016 – 2018"},
            {"school": "Degree", "dates": "2018 – 2022"},
        ],
    }
    _sort_entries_recent_first(data)
    assert [e["role"] for e in data["experience"]] == ["Current", "Mid", "Old"]
    assert [e["school"] for e in data["education"]] == ["Degree", "Diploma"]


def test_sort_handles_missing():
    data = {}                       # no dated sections at all
    _sort_entries_recent_first(data)
    assert data == {}

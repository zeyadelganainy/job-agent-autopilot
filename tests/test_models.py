from jobagent.models import Job


def test_job_id_is_stable_and_case_insensitive_on_url():
    a = Job(source="s", title="Eng", company="c", url="https://x/Job/1")
    b = Job(source="s", title="different", company="other", url="https://x/job/1")
    assert a.job_id == b.job_id          # basis is the lowercased url
    assert len(a.job_id) == 10


def test_job_id_falls_back_to_source_company_title_without_url():
    j = Job(source="s", title="t", company="c", url="")
    assert j.job_id and len(j.job_id) == 10


def test_explicit_job_id_is_kept():
    j = Job(source="s", title="t", company="c", url="u", job_id="fixed123")
    assert j.job_id == "fixed123"


def test_to_dict_roundtrips_fields():
    d = Job(source="s", title="t", company="c", url="u").to_dict()
    assert d["title"] == "t" and d["job_id"]

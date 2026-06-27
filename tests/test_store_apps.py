from jobagent.models import Job
from jobagent.store import Store


def test_apply_flag_retry_and_runs(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    j = Job(source="s", title="T", company="C", url="u")
    s.upsert_job(j)
    s.record_docs(j.job_id, ["/o/r.docx"])          # -> status 'generated'
    assert len(s.ready_to_apply()) == 1

    s.mark_applied(j.job_id)
    assert s.ready_to_apply() == [] and s.today_stats()["applied"] == 1
    assert s.get(j.job_id)["status"] == "applied"

    j2 = Job(source="s", title="T2", company="C", url="u2")
    s.upsert_job(j2)
    s.flag_job(j2.job_id, "rate limit or quota exhausted")
    assert len(s.needs_attention()) == 1
    s.retry_job(j2.job_id)
    assert s.needs_attention() == [] and s.get(j2.job_id)["status"] == "sent"

    rid = s.start_run()
    s.finish_run(rid, status="ok", scanned=5, matched=2, generated=1, needs_attention=0)
    runs = s.list_runs()
    assert runs[0]["scanned"] == 5 and runs[0]["status"] == "ok"
    s.close()


def test_application_crud(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.add_application({"role": "SWE", "company": "Acme", "applied_date": "2026-06-01",
                       "stage": "Applied", "location": "Toronto", "notes": "n"})
    apps = s.list_applications()
    assert len(apps) == 1
    aid = apps[0]["id"]

    s.update_application(aid, {"role": "SWE II", "company": "Acme",
                              "applied_date": "2026-06-02", "stage": "Interview",
                              "location": "Remote", "notes": "n2"})
    a = s.get_application(aid)
    assert a["stage"] == "Interview" and a["role"] == "SWE II"

    s.delete_application(aid)
    assert s.list_applications() == []
    s.close()

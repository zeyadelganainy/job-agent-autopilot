from jobagent.store import Store


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

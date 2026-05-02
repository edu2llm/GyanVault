from gyanvault.db import DBManager

__all__ = ["DBManager"]

if __name__ == "__main__":
    import os

    TEST_DB_PATH = "test_downloads.db"

    def run_tests():
        print("--- Running DBManager Self-Tests ---")

        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)

        db = DBManager(db_path=TEST_DB_PATH)
        if not db.conn:
            print("[FAIL] DBManager failed to initialize.")
            return

        print("[PASS] Initialization")

        url1 = "http://example.com/paper1.pdf"
        db.add_or_update_download(
            complete_url=url1,
            institution="CBSE",
            type="Question Paper",
            year="2023",
            subject="Physics",
            path="output/2023/XII/Physics/paper1.pdf",
            **{"class": "XII"},
        )

        record1 = db.get_download_by_url(url1)
        assert record1 is not None and record1["subject"] == "Physics"
        print("[PASS] Add and Get Record")

        db.update_record(url1, {"subject": "Physics_Updated"})
        record1_updated = db.get_download_by_url(url1)
        assert record1_updated["subject"] == "Physics_Updated"
        print("[PASS] Update Record")

        url2 = "http://example.com/paper2.pdf"
        db.add_or_update_download(
            complete_url=url2,
            institution="CBSE",
            type="Marking Scheme",
            year="2023",
            subject="Chemistry",
            path="output/2023/XII/Chemistry/paper2.pdf",
            **{"class": "XII"},
        )

        physics_results = db.search(subject="Physics_Updated")
        assert len(physics_results) == 1 and physics_results[0]["complete_url"] == url1
        print("[PASS] Search (Exact Match)")

        cbse_2023_results = db.search(institution="CBSE", year="2023")
        assert len(cbse_2023_results) == 2
        print("[PASS] Search (Multiple Criteria)")

        chem_results = db.search(subject="%chem%")
        assert len(chem_results) == 1 and chem_results[0]["complete_url"] == url2
        print("[PASS] Search (LIKE)")

        limited_results = db.search(institution="CBSE", limit=1)
        assert len(limited_results) == 1
        print("[PASS] Search (Limit)")

        db.add_or_update_download(
            complete_url=url1,
            institution="ICSE",
            subject="Physics_Replaced",
        )
        record1_replaced = db.get_download_by_url(url1)
        assert record1_replaced["institution"] == "ICSE" and record1_replaced["subject"] == "Physics_Replaced"
        all_records = db.search()
        assert len(all_records) == 2
        print("[PASS] Add or Update (Replace)")

        db.close()
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        print("[PASS] Cleanup")
        print("\n--- All tests completed successfully! ---")

    try:
        run_tests()
    except AssertionError as e:
        print(f"\n[TEST FAIL] Assertion failed: {e}")
    except Exception as e:
        print(f"\n[CRITICAL FAIL] An unexpected error occurred: {e}")

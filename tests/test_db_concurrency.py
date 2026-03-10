"""tests.test_db_concurrency

Concurrency stress test suite for the thread-safe Database.execute() wrapper
introduced in PR #328.

Validates that the Database._lock mechanism prevents sqlite3.InterfaceError
under realistic concurrent FastAPI-style load.

Load parameters:
  - WORKERS: 20 concurrent threads per test
  - OPS_PER_WORKER: 50 operations per thread (1000 total per test)
  - LOCK_WAIT_THRESHOLD_MS: 500ms max acceptable lock wait
  - INTEGRITY_ROWS: 500 concurrent inserts, all must persist

Concurrency guarantees validated:
  1. Zero InterfaceError under 20-thread concurrent write load
  2. Zero InterfaceError during concurrent reads-during-writes
  3. Lock acquire/release cycles complete without deadlock
  4. FastAPI run_in_threadpool simulation produces correct results
  5. All concurrent writes persisted without loss or corruption
  6. Max lock wait stays under 500ms across 1000+ operations
"""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean

import pytest

from engine.core.database import Database

# ── Load parameters ────────────────────────────────────────────────────────────
WORKERS = 20
OPS_PER_WORKER = 50  # 20 * 50 = 1000 total ops per test
LOCK_WAIT_THRESHOLD_MS = 500
INTEGRITY_ROWS = 500


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Fresh Database for each test."""
    return Database(tmp_path / "concurrency_test.db")


@pytest.fixture()
def db_with_table(db: Database) -> Database:
    """Database with a test table pre-created."""
    db.execute("CREATE TABLE IF NOT EXISTS stress_test (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id INTEGER, value TEXT, ts REAL)")
    return db


class TestConcurrentWrites:
    def test_concurrent_writes_no_interface_error(self, db_with_table: Database) -> None:
        """20 workers writing simultaneously must produce zero InterfaceErrors."""
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(worker_id: int) -> int:
            count = 0
            for i in range(OPS_PER_WORKER):
                try:
                    db_with_table.execute(
                        "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                        (worker_id, f"val-{worker_id}-{i}", time.time()),
                    )
                    count += 1
                except sqlite3.InterfaceError as e:
                    with lock:
                        errors.append(e)
                except Exception:
                    pass  # Other errors (not InterfaceError) are logged but not the focus
            return count

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(worker, i) for i in range(WORKERS)]
            results = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0, f"InterfaceError(s) occurred: {errors}"
        total_written = sum(results)
        assert total_written == WORKERS * OPS_PER_WORKER, f"Expected {WORKERS * OPS_PER_WORKER} writes, got {total_written}"
        print(f"\n ✅ Concurrent writes: {total_written} ops, 0 InterfaceErrors")


class TestConcurrentReadsAndWrites:
    def test_reads_during_writes_no_interface_error(self, db_with_table: Database) -> None:
        """Reader threads running alongside writer threads must produce zero InterfaceErrors."""
        interface_errors: list[str] = []
        lock = threading.Lock()

        def writer(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                try:
                    db_with_table.execute(
                        "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                        (worker_id, f"write-{i}", time.time()),
                    )
                except sqlite3.InterfaceError as e:
                    with lock:
                        interface_errors.append(f"writer-{worker_id}: {e}")

        def reader(worker_id: int) -> None:
            for _ in range(OPS_PER_WORKER):
                try:
                    db_with_table.execute("SELECT COUNT(*) FROM stress_test")
                except sqlite3.InterfaceError as e:
                    with lock:
                        interface_errors.append(f"reader-{worker_id}: {e}")

        threads = []
        for i in range(WORKERS // 2):
            threads.append(threading.Thread(target=writer, args=(i,)))
            threads.append(threading.Thread(target=reader, args=(i + WORKERS // 2,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(interface_errors) == 0, f"InterfaceErrors: {interface_errors}"
        print(f"\n ✅ Concurrent reads+writes: 0 InterfaceErrors across {WORKERS} threads")


class TestLockCycles:
    def test_rapid_lock_cycles_no_deadlock(self, db_with_table: Database) -> None:
        """Rapid sequential lock cycles must complete without deadlock within timeout."""
        errors: list[Exception] = []

        def rapid_cycles(n: int) -> None:
            for i in range(n):
                try:
                    db_with_table.execute("SELECT 1")
                    db_with_table.execute(
                        "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                        (0, f"cycle-{i}", time.time()),
                    )
                except Exception as e:
                    errors.append(e)

        cycles = OPS_PER_WORKER * WORKERS
        thread = threading.Thread(target=rapid_cycles, args=(cycles,))
        thread.start()
        thread.join(timeout=30)  # 30s timeout to detect deadlock

        assert not thread.is_alive(), "Deadlock detected — thread did not complete within 30s"
        interface_errors = [e for e in errors if isinstance(e, sqlite3.InterfaceError)]
        assert len(interface_errors) == 0, f"InterfaceErrors in lock cycles: {interface_errors}"
        print(f"\n ✅ {cycles} lock cycles completed, no deadlock, 0 InterfaceErrors")


class TestFastAPIPattern:
    def test_fastapi_threadpool_simulation(self, db_with_table: Database) -> None:
        """
        Simulates FastAPI's run_in_threadpool pattern where sync route handlers
        execute on a thread pool — the exact concurrency pattern that caused
        InterfaceError before PR #328.
        """
        interface_errors: list[str] = []
        results: list[dict] = []
        lock = threading.Lock()

        # Simulate sync FastAPI route handler
        def fake_route_handler(request_id: int) -> dict:
            """Mimics what a FastAPI sync handler does — runs in threadpool."""
            try:
                # Write (like POST /signals)
                db_with_table.execute(
                    "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                    (request_id, f"signal-{request_id}", time.time()),
                )
                # Read (like GET /signals)
                db_with_table.execute(
                    "SELECT COUNT(*) FROM stress_test WHERE worker_id = ?",
                    (request_id,),
                )
                return {"request_id": request_id, "status": "ok"}
            except sqlite3.InterfaceError as e:
                with lock:
                    interface_errors.append(f"request-{request_id}: {e}")
                return {"request_id": request_id, "status": "error", "error": str(e)}

        # Simulate FastAPI threadpool (default 40 workers)
        request_count = WORKERS * OPS_PER_WORKER
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(fake_route_handler, i) for i in range(request_count)]
            results = [f.result() for f in as_completed(futures)]

        ok_count = sum(1 for r in results if r["status"] == "ok")
        assert len(interface_errors) == 0, f"InterfaceError in FastAPI simulation: {interface_errors[:3]}"
        assert ok_count == request_count
        print(f"\n ✅ FastAPI simulation: {request_count} requests, 0 InterfaceErrors")


class TestDataIntegrity:
    def test_all_concurrent_writes_persisted(self, db_with_table: Database) -> None:
        """
        INTEGRITY_ROWS concurrent inserts must ALL persist without loss or corruption.
        Verifies the lock prevents write-write conflicts from silently dropping rows.
        """
        written_ids: set[int] = set()
        written_lock = threading.Lock()
        errors: list[Exception] = []

        def write_row(row_id: int) -> None:
            try:
                db_with_table.execute(
                    "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                    (row_id, f"integrity-{row_id}", time.time()),
                )
                with written_lock:
                    written_ids.add(row_id)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(write_row, range(INTEGRITY_ROWS)))

        interface_errors = [e for e in errors if isinstance(e, sqlite3.InterfaceError)]
        assert len(interface_errors) == 0, f"InterfaceErrors during integrity test: {interface_errors}"

        # Verify row count in DB matches what we tried to write
        row = db_with_table.fetchone("SELECT COUNT(*) FROM stress_test WHERE value LIKE 'integrity-%'")
        db_count = row[0]
        assert db_count == len(written_ids), f"Data loss: wrote {len(written_ids)} rows, DB has {db_count}"
        assert db_count == INTEGRITY_ROWS, f"Expected {INTEGRITY_ROWS} rows, got {db_count}"
        print(f"\n ✅ Integrity: {db_count}/{INTEGRITY_ROWS} rows persisted without loss")


class TestLockContention:
    def test_lock_wait_time_under_threshold(self, db_with_table: Database) -> None:
        """
        Measure lock acquisition wait time across 1000+ operations.
        Max wait must stay under LOCK_WAIT_THRESHOLD_MS.

        Instruments the Database._lock to capture wait times without
        modifying production code — uses a wrapper approach.
        """
        wait_times_ms: list[float] = []
        wt_lock = threading.Lock()
        interface_errors: list[Exception] = []

        original_lock = db_with_table._lock

        class InstrumentedLock:
            """Wraps threading.Lock to measure acquisition wait time."""

            def acquire(self, blocking=True, timeout=-1):  # noqa: FBT002
                t0 = time.perf_counter()
                result = original_lock.acquire(blocking=blocking, timeout=timeout)
                wait_ms = (time.perf_counter() - t0) * 1000
                with wt_lock:
                    wait_times_ms.append(wait_ms)
                return result

            def release(self):
                return original_lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *args):
                self.release()

        db_with_table._lock = InstrumentedLock()

        def worker(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                try:
                    db_with_table.execute(
                        "INSERT INTO stress_test (worker_id, value, ts) VALUES (?, ?, ?)",
                        (worker_id, f"contention-{i}", time.time()),
                    )
                except sqlite3.InterfaceError as e:
                    interface_errors.append(e)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(worker, range(WORKERS)))

        # Restore original lock
        db_with_table._lock = original_lock

        assert len(interface_errors) == 0, f"InterfaceErrors during contention test: {interface_errors}"
        assert len(wait_times_ms) >= 1000, f"Need 1000+ samples, got {len(wait_times_ms)}"

        avg_ms = mean(wait_times_ms)
        max_ms = max(wait_times_ms)
        p99_ms = sorted(wait_times_ms)[int(len(wait_times_ms) * 0.99)]

        print(f"\n 📊 Lock contention metrics ({len(wait_times_ms)} samples):")
        print(f"    avg wait: {avg_ms:.3f}ms")
        print(f"    max wait: {max_ms:.3f}ms")
        print(f"    p99 wait: {p99_ms:.3f}ms")
        print(f"    threshold: {LOCK_WAIT_THRESHOLD_MS}ms")

        assert max_ms < LOCK_WAIT_THRESHOLD_MS, f"Max lock wait {max_ms:.1f}ms exceeds threshold {LOCK_WAIT_THRESHOLD_MS}ms"
        assert len(interface_errors) == 0

#!/usr/bin/env python3
"""Idempotent demo data seed for Academic OS.

Fills the database with 8 applications, 3 courses with assignments, 5 study tasks,
and 4 documents. Checks for existing data; if applications exist, exits immediately.

Run:
    cd /Users/murunjami/Code/academic-os
    .venv/bin/python scripts/seed_demo.py

With custom data root:
    ACADEMIC_OS_DATA=/tmp/seed-verify .venv/bin/python scripts/seed_demo.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path so imports work when run from anywhere.
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.applications import ApplicationsService
from backend.services.courses import CoursesService
from backend.services.documents import DocumentsService
from backend.services.study import StudyService
from backend.vault import agentic_os_dir


def seed_demo():
    # Resolve data root — same way the app does it.
    data_root = agentic_os_dir()

    # Initialize services.
    apps_service = ApplicationsService(data_root / "data" / "applications")
    courses_service = CoursesService(data_root / "data" / "courses")
    study_service = StudyService(data_root / "data" / "study")
    docs_service = DocumentsService(data_root / "data" / "documents")

    # Idempotency check: if applications already exist, exit.
    existing_apps = apps_service.list_all()
    if existing_apps:
        print("already seeded")
        return

    # --- Applications (8 total) ---
    today = date.today()

    # Undergrad (2)
    app1 = apps_service.add(
        name="University of California, Berkeley",
        org="UC Berkeley",
        type="undergrad",
        status="submitted",
        deadline=(today + timedelta(days=30)).isoformat(),
        url="https://admission.berkeley.edu",
        notes="Early Action deadline",
        requirements=[
            {"label": "Common App essay", "done": True},
            {"label": "SAT scores", "done": True},
            {"label": "Transcript", "done": False},
        ],
    )

    app2 = apps_service.add(
        name="Stanford University",
        org="Stanford",
        type="undergrad",
        status="preparing",
        deadline=(today + timedelta(days=60)).isoformat(),
        url="https://admission.stanford.edu",
        notes="Regular Decision",
        requirements=[
            {"label": "Common App essay", "done": False},
            {"label": "Stanford supplement", "done": False},
            {"label": "ACT scores", "done": True},
            {"label": "Teacher rec letters", "done": False},
        ],
    )

    # Graduate (2)
    app3 = apps_service.add(
        name="MIT Graduate Admissions",
        org="MIT",
        type="grad",
        status="interview",
        deadline=(today + timedelta(days=90)).isoformat(),
        url="https://admissions.mit.edu",
        notes="PhD program in Computer Science",
        requirements=[
            {"label": "GRE scores", "done": True},
            {"label": "Statement of purpose", "done": True},
            {"label": "Research proposal", "done": True},
            {"label": "Letters of recommendation", "done": True},
        ],
    )

    app4 = apps_service.add(
        name="Harvard Graduate School",
        org="Harvard",
        type="grad",
        status="researching",
        deadline=(today + timedelta(days=120)).isoformat(),
        url="https://gradschool.harvard.edu",
        notes="MA in Applied Physics",
        requirements=[
            {"label": "GRE scores", "done": False},
        ],
    )

    # Scholarship (2)
    app5 = apps_service.add(
        name="Fulbright Fellowship",
        org="IIE Fulbright",
        type="scholarship",
        status="submitted",
        deadline=(today + timedelta(days=45)).isoformat(),
        url="https://www.iie.org/fulbright",
        notes="Post-graduate study abroad",
        requirements=[
            {"label": "Application form", "done": True},
            {"label": "Personal statement", "done": True},
            {"label": "Academic transcript", "done": True},
        ],
    )

    app6 = apps_service.add(
        name="National Science Foundation Fellowship",
        org="NSF",
        type="scholarship",
        status="preparing",
        deadline=(today + timedelta(days=75)).isoformat(),
        url="https://www.nsf.gov",
        notes="GRFP for graduate study",
        requirements=[
            {"label": "NSF research proposal", "done": False},
            {"label": "Career goals essay", "done": False},
        ],
    )

    # Exchange (2)
    app7 = apps_service.add(
        name="ERASMUS+ Study Exchange",
        org="European Commission",
        type="exchange",
        status="preparing",
        deadline=(today + timedelta(days=60)).isoformat(),
        url="https://erasmusplus.ec.europa.eu",
        notes="Academic year in Germany",
        requirements=[
            {"label": "Language proficiency cert", "done": False},
        ],
    )

    app8 = apps_service.add(
        name="Study Abroad Program - Japan",
        org="AIFS",
        type="exchange",
        status="decision",
        decision_result="accepted",
        deadline=(today - timedelta(days=15)).isoformat(),
        url="https://www.aifsstudyabroad.com",
        notes="Semester in Tokyo",
        requirements=[
            {"label": "JLPT test", "done": True},
            {"label": "Medical forms", "done": True},
        ],
    )

    # --- Courses (3) and Assignments (2-3 each) ---
    course1 = courses_service.add_course(
        name="Data Structures and Algorithms",
        term="Fall 2024",
        instructor="Prof. Alice Johnson",
    )
    courses_service.add_assignment(
        course_id=course1.id,
        title="Implement Binary Search Tree",
        due=(today + timedelta(days=7)).isoformat(),
        status="todo",
        weight=0.15,
    )
    courses_service.add_assignment(
        course_id=course1.id,
        title="Sorting Algorithm Analysis",
        due=(today + timedelta(days=14)).isoformat(),
        status="todo",
        weight=0.15,
    )
    a1_graded = courses_service.add_assignment(
        course_id=course1.id,
        title="Quiz 1: Trees and Heaps",
        due=(today - timedelta(days=3)).isoformat(),
        status="done",
        grade=92.0,
        weight=0.10,
    )

    course2 = courses_service.add_course(
        name="Linear Algebra",
        term="Fall 2024",
        instructor="Prof. Bob Smith",
    )
    courses_service.add_assignment(
        course_id=course2.id,
        title="Matrix Decomposition Problem Set",
        due=(today + timedelta(days=5)).isoformat(),
        status="todo",
        weight=0.20,
    )
    courses_service.add_assignment(
        course_id=course2.id,
        title="Eigenvalue Analysis Project",
        due=(today + timedelta(days=21)).isoformat(),
        status="todo",
        weight=0.25,
    )

    course3 = courses_service.add_course(
        name="Introduction to Quantum Computing",
        term="Fall 2024",
        instructor="Prof. Carol White",
    )
    courses_service.add_assignment(
        course_id=course3.id,
        title="Quantum Gates Simulation",
        due=(today + timedelta(days=10)).isoformat(),
        status="todo",
        weight=0.30,
    )
    courses_service.add_assignment(
        course_id=course3.id,
        title="Grover's Algorithm Implementation",
        due=(today + timedelta(days=20)).isoformat(),
        status="todo",
        weight=0.30,
    )
    courses_service.add_assignment(
        course_id=course3.id,
        title="Midterm Exam",
        due=(today + timedelta(days=28)).isoformat(),
        status="todo",
        weight=0.40,
    )

    # --- Study Tasks (5) ---
    study_service.add(
        title="Review quantum computing lecture notes",
        day=today.isoformat(),
        priority="high",
        notes="Chapters 3-5 on superposition",
    )

    study_service.add(
        title="Practice linear algebra problem set",
        day=(today + timedelta(days=1)).isoformat(),
        priority="normal",
    )

    study_service.add(
        title="Prepare Stanford supplement essay",
        due=(today + timedelta(days=45)).isoformat(),
        priority="high",
        notes="Focus on why Stanford specifically",
    )

    study_service.add(
        title="Study for Linear Algebra midterm",
        day=(today + timedelta(days=7)).isoformat(),
        due=(today + timedelta(days=14)).isoformat(),
        priority="high",
        notes="Make practice test",
    )

    task_done = study_service.add(
        title="Proofread CV for scholarship applications",
        day=(today - timedelta(days=1)).isoformat(),
        priority="normal",
        done=True,
        notes="Completed review; ready to submit",
    )

    # --- Documents (4) ---
    doc1 = docs_service.add(
        title="Common Application Essay - Intellectual Vitality",
        kind="essay",
        status="final",
        tags=["common-app", "undergrad", "ready"],
        linked_application_ids=[app1.id],
        notes="Final version discussing programming journey.",
    )

    doc2 = docs_service.add(
        title="Professional CV - 2024 Edition",
        kind="cv",
        status="final",
        tags=["applications", "professional"],
        linked_application_ids=[app3.id, app5.id],
        notes="Updated with research experience.",
    )

    doc3 = docs_service.add(
        title="Undergraduate Transcript",
        kind="transcript",
        status="draft",
        tags=["official", "pending"],
    )

    # Bump version on transcript
    docs_service.bump_version(doc3.id, "Requested official sealed copy from registrar")

    doc4 = docs_service.add(
        title="Letter of Recommendation - Prof. Johnson",
        kind="lor",
        status="in_review",
        tags=["faculty", "strong-writer"],
    )

    # Print counts
    print(f"Applications: {len(apps_service.list_all())}")
    print(f"Courses: {len(courses_service.list_courses())}")
    assignments = courses_service.list_assignments()
    print(f"Assignments: {len(assignments)}")
    print(f"Study Tasks: {len(study_service.list_all())}")
    print(f"Documents: {len(docs_service.list_all())}")


if __name__ == "__main__":
    seed_demo()

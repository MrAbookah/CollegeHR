from decimal import Decimal

# Grade scale lives in code, not a table: it changes once a decade and a
# change deserves code review.
GRADE_POINTS = {
    "A": Decimal("4.00"), "A-": Decimal("3.70"),
    "B+": Decimal("3.30"), "B": Decimal("3.00"), "B-": Decimal("2.70"),
    "C+": Decimal("2.30"), "C": Decimal("2.00"), "C-": Decimal("1.70"),
    "D+": Decimal("1.30"), "D": Decimal("1.00"),
    "F": Decimal("0.00"),
}
NON_GPA_GRADES = {"P", "W", "I"}
ALL_GRADES = list(GRADE_POINTS) + sorted(NON_GPA_GRADES)
PASSING = set(GRADE_POINTS) - {"F"} | {"P"}

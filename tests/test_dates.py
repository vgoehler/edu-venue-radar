from datetime import date

from edu_venue_radar.dates import date_lines, deadline_candidates, find_dates, month_of


def test_find_dates_reads_the_common_spellings():
    text = "2026-12-07, 07.12.2026, 7 December 2026, Dec 07, 2026, 7. Dezember 2026, December 7th, 2026"
    assert [f.when for f in find_dates(text)] == [date(2026, 12, 7)] * 6


def test_find_dates_skips_impossible_dates():
    assert find_dates("31.02.2026 and 2026-13-01") == []


def test_candidates_need_a_keyword_nearby_and_a_future_date():
    text = "Workshop proposals: Dec 07, 2026. Registration opens 1 March 2027. Old deadline 5 January 2025."
    found = deadline_candidates(text, ["workshop", "deadline"], today=date(2026, 10, 23), window=40)
    assert [(c.when, c.keyword) for c in found] == [(date(2026, 12, 7), "workshop")]


def test_candidates_rank_by_keyword_order():
    text = "paper deadline 18 January 2027 ... workshop proposals due 7 December 2026"
    found = deadline_candidates(text, ["workshop", "deadline"], today=date(2026, 10, 23), window=25)
    assert [c.keyword for c in found] == ["workshop", "deadline"]


def test_candidates_ignore_dates_far_ahead():
    found = deadline_candidates("deadline 1 May 2031", ["deadline"], today=date(2026, 10, 23))
    assert found == []


def test_month_of_reads_months_and_seasons():
    assert month_of("early November 2027") == 11
    assert month_of("autumn 2027") == 9
    assert month_of("Herbst") == 9
    assert month_of("2027") is None


def test_date_first_tables_take_the_label_after_the_date():
    text = "Datum Deadline 03.03.2027 Einreichung von Workshops / Tutorials 24.03.2027 Benachrichtigung über Workshops"
    found = deadline_candidates(text, ["einreichung", "deadline"], today=date(2026, 10, 23), layout="date-first")
    assert [(c.when, c.keyword) for c in found] == [(date(2027, 3, 3), "einreichung")]


# Contexts as the crawler stored them on 23.10.2026.
EDUCON = (
    "Important Dates & Information Oct 08, 2026 Alternative Session Proposal Submission (Special Session) "
    "Oct 26, 2026 Alternative Session Proposal Notification (Special Session) Oct 30, 2026 Abstract Submission Deadline "
    "(all paper formats) Nov 06, 2026 Abstract Notifications Dec 07, 2026 Preliminary Paper Submission Deadline "
    "Dec 07, 2026 Submission of Proposals for Workshops, Panels, and Posters Jan 11, 2027 Paper Decision Notifications "
    "Feb 15, 2027 Final Camera-Ready Manuscript Deadline, Author Registration Deadline"
)
SOTL_COMMONS = (
    "Proposal Submission Deadline: October 23, 2026 Notice of Proposal Acceptance: Notifications sent on December 7, 2026 "
    "Confirmation of Proposal Acceptance : January 15, 2027 To remain in the Conference Program, Presenters must register "
    "by January 31, 2027 Conference Review Platform (Oxford Abstracts)"
)
ITK = (
    "Conference web page https://itk-konferenssi.fi/en Submission deadline November 2, 2026 Topics: educational technology "
    "ITK2027 – A New Contract for Learning 21–23 April 2027 | Tampere Hall, Tampere, Finland "
    "Call for Presentations deadline: 2 November 2026 ITK2027 invites educators"
)
TODAY = date(2026, 10, 23)


def whens(found):
    return sorted(c.when.isoformat() for c in found)


def test_notifications_and_follow_ups_are_not_deadlines():
    found = deadline_candidates(EDUCON, ["workshop", "special session", "abstract", "deadline"], TODAY)
    assert whens(found) == ["2026-10-30", "2026-12-07"]
    found = deadline_candidates(SOTL_COMMONS, ["proposal", "deadline", "submission"], TODAY)
    assert whens(found) == ["2026-10-23"]


def test_event_days_are_not_deadlines():
    koli = (
        "Doctoral consortium: November 3 – 4, 2026, Joensuu, Finland Pre-conference workshop: November 4, 2026, Joensuu, "
        "Finland Conference: November 5 – 8, 2026, Koli, Finland"
    )
    icce = "tutorials) will be conducted on the first two days and the main conference will begin on December 2nd 2026."
    for text in (koli, icce):
        assert deadline_candidates(text, ["submission", "workshop", "deadline"], TODAY) == []


def test_a_submission_label_wins_over_a_nearby_event_word():
    csedu = (
        "Upcoming Submission Deadlines Regular Paper Submission: November 17, 2026 Position/Regular Paper Submission: "
        "December 21, 2026 (See Important Dates for more information) CSEDU, the International Conference on Computer"
    )
    assert whens(deadline_candidates(csedu, ["paper submission", "deadline"], TODAY)) == ["2026-11-17", "2026-12-21"]
    gmw = "Neueste Beiträge Call for Papers “Mediendidaktik im Zeitalter Künstlicher Intelligenz” (15.11.2026) Souverän vernetzt"
    assert whens(deadline_candidates(gmw, ["call", "einreichung"], TODAY)) == ["2026-11-15"]
    assert whens(deadline_candidates("Full paper submission (main conference): 1 December 2026", ["submission"], TODAY)) == [
        "2026-12-01"
    ]


def test_date_first_labels_are_checked_too():
    text = (
        "03.03.2027 Einreichung von Workshops / Tutorials 24.03.2027 Benachrichtigung über Einreichungen "
        "07.04.2027 Einreichung von Kurz- und Langbeiträgen 01.09.2027 Tagung"
    )
    found = deadline_candidates(text, ["einreichung", "tagung", "benachrichtigung"], TODAY, layout="date-first")
    assert whens(found) == ["2027-03-03", "2027-04-07"]


def test_candidates_stop_at_the_conference_start():
    keywords = ["call for presentations", "workshop", "deadline"]
    assert "2027-04-23" in whens(deadline_candidates(ITK, keywords, TODAY))
    assert whens(deadline_candidates(ITK, keywords, TODAY, before=date(2027, 4, 21))) == ["2026-11-02"]


def test_date_lines_keep_only_sentences_with_dates():
    text = "Latest news: our new podcast is out. Submission deadline: 2 November 2026. Notification 7 December 2026."
    assert date_lines(text) == ["Notification 7 December 2026.", "Submission deadline: 2 November 2026."]

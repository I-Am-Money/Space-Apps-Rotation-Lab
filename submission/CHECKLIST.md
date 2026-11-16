# Submission checklist (Person 3)

Source: NASA Space Apps "Project Submission Guide", https://www.spaceappschallenge.org/resources/project-submission-guide/
(read 2026-11-15). Quotes are copied word for word.

## What the guide says

- Slides: "no more than seven slides (including the title and intro slides)". "Adhere to the 30-second and
  7-slide limits. Projects that exceed these limits will not be eligible for Global Judging."
- Slide content must address: "Team name", "Names of team members", "The challenge your team selected".
- Under 18: "Project demonstrations and final projects may not include any images, video, audio, or other
  likeness to persons under 18 years old per the NASA Space Apps Terms & Conditions."
- Deadline: "Submit for Judging" before Sunday, November 15 at 11:59 p.m. local time of the Local Event.

## Open decision (team to verify with the Local Lead)

The guide asks for member names on the slides, but the team rule is no team member names anywhere. The guide
itself forbids only images, video, audio and likeness of under-18 participants, not names. Until the team or
the Local Lead decides, the deck uses **the team name only** (Build Spec v4 A9), with a placeholder line
"Team members: [team to confirm with Local Lead]".

## Rules for the deck and project page

- No faces, photos, voices or video of people. The app is shown as screenshots or real screen recordings only.
  An AI-generated farmland shot in the video must carry a visible AI-generated watermark and be disclosed in the
  portal's AI section.
- No village name. No emails.
- Every number on a slide comes from the app or `config/validation/results.csv`. Anything unverified is marked "team to verify".
- Nobody on Claude Code submits anything to the Space Apps portal. The team clicks Submit.

## Status (2026-11-15, evening)

Written and in this folder:

- `deck.md`: text for 7 slides, the notes behind the validation slide, and the 30-second video script.
- `project_page.md`: summary, description, NASA data, other data, use of AI, links.

Still for the team to do (none of it can be done from the repo):

1. Fill in the [square bracket] lines that are left: the video and slide links. The team name is MACS, the
   challenge title on the portal is "Field Shift: Adapting Farms with NASA Data", and the hosted app is
   https://space-apps-rotation-lab-production.up.railway.app.
2. Decide the member-names question above with the Local Lead.
3. Take new screenshots from the current app. `assets/screens/` still shows the earlier India build.
4. Build the slides (7 or fewer) and record the video (30 seconds or less, screen and captions only, no voices).
5. Check the repo is public and the hosted app opens without a login. Wake the app right before submitting.
6. A team member clicks Submit before 11:59 p.m. local time.

Last look before submitting: no faces, voices or names in the slides, the video or the screenshots (check
browser tabs, bookmarks and account avatars in screen recordings), and no number that is not in
`config/validation/results.csv` or on the app screen shown.

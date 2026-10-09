import type { ResumeTemplate } from './types'

export const template: ResumeTemplate = {
  id: 'grad-academic-cv',
  label: 'Graduate Academic CV',
  hint: 'For graduate students applying to PhD programs, fellowships, postdocs, or academic jobs, where a multi-page CV is expected.',
  body: `[Full Name]
[City, State] | [Email] | [Phone] | [LinkedIn or portfolio URL, optional]

EDUCATION
[Degree, e.g. PhD / MS / BA] in [Field], [University], [City, State] ([Start year]-[End year or expected year])
- Thesis or dissertation: [Title] (advisor: [Advisor name], status: [in progress / defended, Year])
- Committee: [Member name], [Member name], [Member name]
- GPA: [GPA, optional] | Honors: [Honors, optional]
[Degree] in [Field], [University], [City, State] ([Start year]-[End year])
- [Thesis title, honors, or relevant coursework, optional]

RESEARCH INTERESTS
- [Primary research area]
- [Secondary area or method]
- [Question or problem you want to work on]

RESEARCH EXPERIENCE
[Position title], [Lab or group name], [University or institution], [City, State] ([Start month year]-[End month year or Present])
Supervisor: [Name of PI or advisor]
- [Action verb] [research question or project] using [method, tool, or dataset] [result, with a number if you have one]
- [Action verb] [what you built, collected, or analyzed] [scale: sample size, data volume, or duration]
- [Action verb] [how you worked with others: mentored, coordinated, or co-authored] [outcome]

[Position title], [Lab or group name], [Institution], [City, State] ([Start month year]-[End month year])
- [Action verb] [what you did] [result, with a number if you have one]

PUBLICATIONS
Peer-reviewed articles
- [Author list, with your name in the format used by your field]. ([Year]). [Article title]. [Journal name], [volume]([issue]), [pages or article number]. [DOI or URL]
Manuscripts under review or in preparation
- [Author list]. ([Year]). [Working title]. [Status: under review at Journal / in preparation]
Citation format: [APA / MLA / Chicago / field-specific style]. Use the same style for every entry.

PRESENTATIONS
- [Presenter name(s)]. ([Year, Month]). [Title of talk or poster]. [Conference or venue name], [City, State or Virtual]. [Type: oral / poster / invited talk]
- [Presenter name(s)]. ([Year, Month]). [Title]. [Conference or venue], [Location]. [Type]

TEACHING EXPERIENCE
[Role: Instructor of record / Teaching assistant / Guest lecturer], [Course number and title], [University] ([Term and year])
- [Action verb] [what you taught, led, or graded] [class size or number of sections]
- [Action verb] [course material or method you designed] [result: evaluation score, student outcome]
[Role], [Course], [University] ([Term and year])
- [Action verb] [what you did] [number of students]

GRANTS AND FELLOWSHIPS
- [Grant or fellowship name], [Funding body] ([Year or Year-Year]), [Amount, optional]
- [Grant or fellowship name], [Funding body] ([Year]), [role: PI / co-PI / recipient]

AWARDS
- [Award name] ([Year]), [scope: department / university / regional / national]
- [Award name] ([Year]), [scope]

SKILLS
Methods: [Research methods or techniques]
Software and tools: [Software, programming languages, instruments]
Languages: [Language] ([proficiency level])

REFERENCES
[Reference name], [Title], [Department], [University or organization]
[Email] | [Phone, optional] | Relationship: [advisor / committee member / collaborator]
[Reference name], [Title], [Department], [University or organization]
[Email] | [Phone, optional] | Relationship: [relationship]

TIPS (delete before sending)
- Use reverse-chronological order inside every section, newest entry first.
- Start each bullet with a strong action verb (designed, analyzed, developed, taught, secured) and add a number where you can.
- Follow one citation style for all publications and presentations, and bold or underline your own name consistently.
- Put the sections your target values most near the top. For a research position, move Publications above Research Experience.
- Ask each reference for permission first, and delete this block, empty sections, and any bracket you did not fill in.`,
}

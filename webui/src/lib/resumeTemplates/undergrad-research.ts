import type { ResumeTemplate } from './types'

export const template: ResumeTemplate = {
  id: 'undergrad-research',
  label: 'Undergrad Research',
  hint: 'For undergraduates applying to research assistant positions, labs, and REU programs.',
  body: `[Full Name]
[City, State]
[Email] | [Phone] | [LinkedIn or portfolio URL, optional]

EDUCATION
[University name], [City, State]
[Degree type] in [Major], [Minor, optional]. Expected [Month Year]
- GPA: [GPA, include only if 3.5 or higher] | Major GPA: [Major GPA, optional]
- [Scholarship or program, e.g. honors college, optional]

RESEARCH EXPERIENCE
[Lab name], [University], [City, State]. [Month Year] to [Month Year or Present]
[Your title, e.g. Undergraduate Research Assistant], supervised by [PI name and title]
- [Action verb] [the research question or project goal] using [method or technique]
- [Action verb] [what you did, e.g. collected, analyzed, or prepared samples or data] [result, with a number if you have one]
- [Action verb] [tool, protocol, or software you used] to [outcome]
- [Hours per week and number of semesters, if relevant]

[Second lab or research project name], [University or organization]. [Month Year] to [Month Year]
[Your title], supervised by [PI or mentor name]
- [Action verb] [what you did] [result, with a number if you have one]
- [Action verb] [method or contribution] [outcome]

RELEVANT COURSEWORK
[Course name], [Course name], [Course name], [Course name], [Course name], [Course name]

TECHNICAL AND LAB SKILLS
Lab techniques: [Technique], [Technique], [Technique]
Software and programming: [Language or tool], [Language or tool], [Statistics package]
Instruments and equipment: [Instrument], [Instrument]

PRESENTATIONS AND POSTERS
- [Presentation or poster title], [Event name], [Location or institution], [Month Year] ([oral / poster])
- [Second presentation or poster title], [Event name], [Month Year]

HONORS AND AWARDS
- [Award name] ([Year]), [scope: school / state / national]
- [Scholarship or Dean's List] ([Semesters or Year])

TIPS (delete before sending)
- Start every bullet with a strong past-tense action verb (analyzed, designed, calibrated, cultured, coded). Use present tense only for current work.
- Name the method, not just the topic. Labs want to see what you can already do at the bench or in code.
- Quantify where you can: samples processed, data set size, hours per week, number of trials, accuracy gained.
- List the PI's name exactly as it appears on the lab website, and confirm they are willing to be a reference before you list them.
- Keep to one page, reverse-chronological order, plain text. Tailor the coursework and skills lines to match each lab's posting.`,
}

import type { ResumeTemplate } from './types'

export const template: ResumeTemplate = {
  id: 'undergrad-internship',
  label: 'Undergrad internship',
  hint: 'For undergraduates applying to internships with limited work history.',
  body: `[Full Name]
[City, State] | [Email] | [Phone] | [LinkedIn or portfolio URL, optional]

EDUCATION
[University name], [City, State]
[Degree type and major], [Minor, optional]. Expected graduation: [Month Year]
- GPA: [X.XX / 4.00] (include only if 3.5 or higher)
- Relevant coursework: [Course 1], [Course 2], [Course 3], [Course 4]
- [Honors, Dean's List, or scholarship name] ([Year])

EXPERIENCE
[Job or internship title], [Organization], [City, State] | [Month Year] - [Month Year or Present]
- [Action verb] [what you did] [result, with a number if you have one]
- [Action verb] [what you did] [result, with a number if you have one]
- [Action verb] [what you did] [tool or skill used] [result]

[Job or internship title], [Organization], [City, State] | [Month Year] - [Month Year]
- [Action verb] [what you did] [result, with a number if you have one]
- [Action verb] [what you did] [result, with a number if you have one]

PROJECTS
[Project name] | [Course, club, or personal] | [Month Year] - [Month Year]
- [Action verb] [what you built or studied] using [tools or methods]
- [Result or outcome, with a number if you have one], [link to code or demo, optional]

[Project name] | [Course, club, or personal] | [Month Year]
- [Action verb] [what you built or studied] using [tools or methods]

LEADERSHIP AND ACTIVITIES
[Role], [Club or organization] | [Month Year] - [Month Year or Present]
- [Action verb] [what you led or organized] [scope: number of members, events, or dollars]
[Role], [Team, volunteer group, or organization] | [Month Year] - [Month Year]
- [Action verb] [what you did] [result]

SKILLS
Technical: [Software, tools, programming languages, lab or field methods]
Languages: [Language] ([proficiency: native / fluent / conversational / basic])
Certifications: [Certification name] ([Year]), [optional]

TIPS (delete before sending)
- Keep it to one page. Cut older or weaker items before shrinking the font below 10 pt.
- Start every bullet with a strong past-tense action verb (built, analyzed, organized, led, reduced). Use present tense only for current roles.
- Quantify where you can: hours, people, dollars, percentages, users. If you have no number, state the outcome plainly.
- List sections and entries in reverse-chronological order, and put Education first while you have little work history.
- Match keywords from the internship posting (tools, skills, course names) in your bullets and skills line, and save the file as a PDF named [FirstName-LastName-Resume].
`,
}

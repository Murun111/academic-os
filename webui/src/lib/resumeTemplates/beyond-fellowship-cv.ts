import type { ResumeTemplate } from './types'

export const template: ResumeTemplate = {
  id: 'beyond-fellowship-cv',
  label: 'Fellowship CV',
  hint: 'For graduate students and early researchers applying to fellowships and research grants.',
  body: `[Full Name]
[City, State] | [Email] | [Phone] | [LinkedIn or portfolio URL, optional]

EDUCATION
[Degree, major] | [University], [City, State] | [Start year]-[End year or expected]
- Thesis or dissertation: [Title], advisor [Advisor name]
- GPA [number, only if strong] | Honors: [honor, scope]
[Prior degree, major] | [University] | [Start year]-[End year]

POSITIONS
[Title, e.g. research assistant, teaching assistant] | [Lab or department], [Institution] | [Start year]-[End year]
- [Action verb] [what you did] [result, with a number if you have one]
- [Action verb] [method, tool, or technique] to [goal], resulting in [outcome]

RESEARCH AND PROJECTS
[Project title] | [Lab, course, or independent] | [Start year]-[End year]
- [Research question or goal in one line]
- [Action verb] [your method and your specific role] [result, with a number if you have one]
- [Data, tools, or collaborators involved]

PUBLICATIONS AND OUTPUTS
- [Authors, in published order]. ([Year]). [Title]. [Journal or venue], [volume/pages]. [Status: published / under review / in preparation]
- [Conference talk or poster title], [Conference name], [City], [Year]
- [Preprint, dataset, software, or report], [Link or repository]

FUNDING RECEIVED
- [Grant or fellowship name], [Funder] ([Year]), [amount, if you want to share it]
- [Travel or research award], [Funder] ([Year])

AWARDS
- [Award name] ([Year]), [scope: school / state / national]
- [Scholarship name] ([Year]), [selection basis]

SERVICE AND LEADERSHIP
- [Role], [Organization or committee] ([Start year]-[End year]): [what you did and the scale, e.g. number of people]
- [Peer review, mentoring, or outreach activity] ([Year])

LANGUAGES
- [Language] ([proficiency: native / fluent / professional / basic])
- [Language] ([proficiency])

TIPS (delete before sending)
- Check the funder's page limit and section order first, then match their wording for each criterion.
- Use reverse-chronological order inside every section, newest first.
- Start each bullet with a strong action verb (designed, analyzed, built, led) and add a number where you can.
- Mark each publication as published, under review, or in preparation. Never blur the status.
- List your own contribution on every project, not just the team's. Reviewers look for what you did.
`,
}

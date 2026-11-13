<?php

declare(strict_types=1);

/**
 * The 20 permanent departments. Order is the masthead order; slugs are permanent URLs.
 * Each carries its mission paragraph and an opening brief that seeds the article stream.
 * Departments 2-8 are the principles the Buyer's Brief scorecard rates products against.
 */
return [
    [
        'slug' => 'the-human-multiplier',
        'name' => 'The Human Multiplier',
        'tagline' => 'Good AI + teachable human = optimized ROI.',
        'mission' => 'The best returns from AI do not come from the model alone or the person alone. They come from the pairing: a capable system working beside someone willing to learn how to direct it, check it, and improve on it. This department documents teams that got that pairing right. Every case study names the task, the baseline, the method, and the measured result, so a reader can judge whether the gain would survive in their own organization.',
        'opener' => [
            'title' => 'The pairing is the product',
            'dek' => 'Why this magazine starts with people, and what a case study has to show before we print it.',
            'body' => 'Most accounts of AI at work describe the tool. The more useful account describes the pair: what the person brought, what the system brought, and what changed when the two were put together deliberately rather than by accident.',
            'questions' => [
                'What was the baseline before the pairing, and who measured it?',
                'What did the human have to learn, and how long did that take?',
                'Would the result hold with a different team, or did it depend on one exceptional person?',
            ],
        ],
    ],
    [
        'slug' => 'clean-intelligence',
        'name' => 'Clean Intelligence',
        'tagline' => 'Ethical AI in practice: energy, water, carbon, and minimal-impact design.',
        'mission' => 'Every answer a model gives is paid for in electricity, cooling water, and hardware that had to be manufactured. This department treats those costs as engineering facts rather than slogans. We report how energy, water, and carbon are actually measured, where the published figures are solid and where they are guesswork, and which design choices reduce the impact of a workload without reducing its usefulness.',
        'opener' => [
            'title' => 'Count the watts before you count the wins',
            'dek' => 'Environmental cost is a design input. We intend to treat it like one.',
            'body' => 'A workload that could run on a small model and runs on a large one instead is waste, whatever the result looks like on a slide. The discipline of minimal-impact design begins with knowing what a task really requires and refusing to spend more than that.',
            'questions' => [
                'Was the energy figure measured at the wall, estimated from a model card, or assumed?',
                'What is the smallest system that would do this job acceptably?',
                'Who bears the water and carbon cost, and do they appear anywhere in the business case?',
            ],
        ],
    ],
    [
        'slug' => 'pro-human-defined',
        'name' => 'Pro-Human Defined',
        'tagline' => 'Augmentation versus replacement, and how each affects overall ROI.',
        'mission' => 'Pro-human is a claim that needs a definition before it means anything. This department draws the line between augmentation, where a system extends what a person can do and leaves them accountable for the outcome, and replacement, where the person is removed from the work. We examine what each choice does to quality, resilience, institutional knowledge, and total return, including the costs that arrive a year after the decision.',
        'opener' => [
            'title' => 'A working definition of pro-human',
            'dek' => 'Augmentation and replacement are different investments with different risk profiles.',
            'body' => 'Replacement is easy to model: a salary line disappears. Augmentation is harder to model and often worth more, because the person who remains can catch errors, handle exceptions, and carry what the organization knows. A fair comparison has to price both sides honestly.',
            'questions' => [
                'Who is accountable for the output once the system is in place?',
                'What knowledge leaves the building if the role disappears?',
                'Which costs of replacement show up only after the first year?',
            ],
        ],
    ],
    [
        'slug' => 'lean-compute',
        'name' => 'Lean Compute',
        'tagline' => 'Getting the most from low-powered CPUs: quantization, small models, CPU-only inference.',
        'mission' => 'Not every organization has a rack of accelerators, and most tasks do not need one. This department is a working guide to doing real work on modest processors: quantized weights, small and distilled models, efficient runtimes, and inference that never touches a GPU. We publish the settings, the hardware, and the trade-offs in quality, so results can be reproduced on the machine already under the desk.',
        'opener' => [
            'title' => 'The machine you already own',
            'dek' => 'A great deal of useful AI fits on ordinary hardware. Our job is to show exactly how.',
            'body' => 'The assumption that serious AI requires serious hardware is often untested. Shrinking a model costs some accuracy and buys independence, lower running cost, and a much smaller energy bill. Whether that trade is worth making depends on the task, which is why we will always name the task.',
            'questions' => [
                'What hardware was used, down to the processor and memory?',
                'How much quality was given up, measured on what?',
                'Is the speed acceptable for the person actually waiting on the answer?',
            ],
        ],
    ],
    [
        'slug' => 'small-footprint',
        'name' => 'Small Footprint',
        'tagline' => 'Storage efficiency: model compression, compact vector stores, data minimization.',
        'mission' => 'Data kept is data that must be stored, secured, backed up, and eventually explained to a regulator. This department covers the storage side of efficient AI: compressing models, keeping vector indexes compact, and collecting less in the first place. We look for approaches that lower cost and risk together, and we say plainly when a compression technique costs more in accuracy than it saves in disk.',
        'opener' => [
            'title' => 'Keep less, know more',
            'dek' => 'Storage discipline is a cost control and a privacy control at the same time.',
            'body' => 'The cheapest byte to protect is the one never collected. A compact index and a deliberate retention policy do more for a deployment than another tier of storage, and they make the system easier to audit.',
            'questions' => [
                'What is stored, for how long, and who decided that?',
                'What does retrieval quality look like before and after compression?',
                'Could this system do its job with less data than it holds today?',
            ],
        ],
    ],
    [
        'slug' => 'at-the-edge',
        'name' => 'At the Edge',
        'tagline' => 'Local and edge deployment that cuts datacenter dependence, latency, and cost.',
        'mission' => 'When the model runs where the work happens, data stays put, responses arrive without a round trip, and a network outage stops being an AI outage. This department follows local and edge deployments in offices, factories, clinics, and vehicles. We report what it takes to run and maintain them, what they save, and the operational burdens that a hosted service would otherwise have carried.',
        'opener' => [
            'title' => 'Closer to the work',
            'dek' => 'Local deployment trades a monthly bill for an operational responsibility. We will examine both.',
            'body' => 'Running locally changes the cost structure and the failure modes. The latency and sovereignty benefits are real. So is the work of patching, monitoring, and updating machines that nobody in a datacenter is watching for you.',
            'questions' => [
                'What happens to this system when the network goes down?',
                'Who updates the model on the device, and how often?',
                'What did the move away from hosted inference cost in staff time?',
            ],
        ],
    ],
    [
        'slug' => 'ground-truth',
        'name' => 'Ground Truth',
        'tagline' => 'Accuracy, verifiability, and determinism: testing, reproducibility, grounding.',
        'mission' => 'A system that is usually right is only useful if you can tell when it is wrong. This department is about knowing: test methods that reflect real work, results that can be reproduced, outputs grounded in sources a person can check, and determinism where the task demands the same answer twice. We favor methods a small team can run themselves over benchmarks that only a laboratory can repeat.',
        'opener' => [
            'title' => 'How do you know?',
            'dek' => 'The question we will put to every accuracy claim that crosses this desk.',
            'body' => 'Confidence is cheap and verification is work. An organization that cannot test its own system is relying on the vendor\'s word, and a result that cannot be reproduced is an anecdote. This department exists to make checking practical.',
            'questions' => [
                'Was the system tested on the organization\'s own work or on a public benchmark?',
                'Can someone else rerun the test and get the same result?',
                'When the system is wrong, how does anyone find out?',
            ],
        ],
    ],
    [
        'slug' => 'glass-box',
        'name' => 'Glass Box',
        'tagline' => 'Transparency and auditability: logging, explainability, audit trails.',
        'mission' => 'Decisions made with AI have to be reconstructable after the fact: what went in, what came out, which version produced it, and who approved the result. This department covers the practice of building systems that can be inspected. We look at logging that is useful rather than merely voluminous, explanations that hold up under questioning, and audit trails that would satisfy someone with the authority to ask.',
        'opener' => [
            'title' => 'Show your work',
            'dek' => 'If a decision cannot be reconstructed, it cannot be defended.',
            'body' => 'Auditability is rarely missed until the day it is needed, and by then it is too late to add. The systems worth trusting record enough to answer a hard question months later, and they do it by design.',
            'questions' => [
                'Can this output be traced to its inputs, model version, and reviewer?',
                'Does the explanation describe what the system did, or only sound plausible?',
                'Who reads the logs, and what would make them act?',
            ],
        ],
    ],
    [
        'slug' => 'the-written-word',
        'name' => 'The Written Word',
        'tagline' => 'Text generation for drafting, summarization, knowledge work, and its limits.',
        'mission' => 'Text is where most organizations meet AI first. This department covers drafting, summarizing, searching, and reasoning over documents, with attention to where the technology helps and where it quietly degrades the work. We report on workflows that keep a knowledgeable person responsible for what is published, and we are specific about the limits: invented facts, flattened voice, and summaries that drop the one detail that mattered.',
        'opener' => [
            'title' => 'A draft is not a document',
            'dek' => 'Generated text is a starting point. The department is about what happens next.',
            'body' => 'Fluent prose reads as finished whether or not it is correct. The useful workflows treat generated text as material for a person who knows the subject, and they are built so that person has the time and the means to check it.',
            'questions' => [
                'Who verifies the facts in the draft, and against what?',
                'What did the summary leave out?',
                'Does the finished piece still sound like the organization that signed it?',
            ],
        ],
    ],
    [
        'slug' => 'synthetic-studio',
        'name' => 'Synthetic Studio',
        'tagline' => 'Video, image, and audio generation, including provenance and rights.',
        'mission' => 'Generated media has moved from novelty to production tool, and it brings questions that text does not. This department covers image, video, and audio generation as working crafts, alongside the obligations that come with them: establishing where a piece of media came from, whose work and likeness it draws on, how it should be labeled, and what consent is owed before a voice or a face is synthesized.',
        'opener' => [
            'title' => 'Made, and marked as made',
            'dek' => 'Capability and provenance belong in the same conversation.',
            'body' => 'A generated image is easy to produce and hard to account for. Organizations using synthetic media need to know what they are entitled to publish, how to label it, and how to prove its origin when someone asks.',
            'questions' => [
                'Can the origin of this media be demonstrated to a third party?',
                'Whose work, voice, or likeness does it depend on, and did they agree?',
                'How will the audience know it was generated?',
            ],
        ],
    ],
    [
        'slug' => 'pocket-ai',
        'name' => 'Pocket AI',
        'tagline' => 'AI apps for mobile devices and on-device models.',
        'mission' => 'The most personal computer most people own is a phone, and models now run on it directly. This department covers mobile AI applications and on-device inference: what works within the limits of battery, memory, and heat, what stays private because it never leaves the handset, and how to tell an app that runs locally from one that only looks as if it does.',
        'opener' => [
            'title' => 'The model in your pocket',
            'dek' => 'On-device AI changes what can stay private. It also has hard physical limits.',
            'body' => 'A phone is a constrained machine with a small battery and a user who notices heat. Running a model on it is an exercise in restraint, and the reward is an assistant that works offline and keeps personal data on the device.',
            'questions' => [
                'Does the app run on the device, or send the data elsewhere?',
                'What does it cost in battery over a working day?',
                'What can it do with no connection at all?',
            ],
        ],
    ],
    [
        'slug' => 'the-roi-ledger',
        'name' => 'The ROI Ledger',
        'tagline' => 'Hard measurement: cost per task, payback periods, and failed projects dissected.',
        'mission' => 'Return on investment is the claim most often made about AI and least often shown. This department does the arithmetic. We work through cost per task, total cost of ownership, and payback periods using figures that sources are willing to stand behind, and we give equal space to projects that failed, because a clearly explained failure teaches more than a success story with the numbers removed.',
        'opener' => [
            'title' => 'Open the books',
            'dek' => 'What we will ask to see before calling anything a return.',
            'body' => 'A productivity claim without a baseline, a cost, and a time period is marketing. The ledger is the place for the full calculation, including the staff time, the rework, and the project that was quietly switched off.',
            'questions' => [
                'What did one completed task cost before and after, all costs included?',
                'How long until the investment pays for itself, on whose assumptions?',
                'What went wrong, and what would the team do differently?',
            ],
        ],
    ],
    [
        'slug' => 'the-teachable-workforce',
        'name' => 'The Teachable Workforce',
        'tagline' => 'Training, upskilling, and change management.',
        'mission' => 'The human half of the equation does not happen by itself. This department covers how people actually become good at working with AI: training that sticks, time set aside to practice, managers who model the behavior, and change handled so that staff are participants and not subjects. We pay particular attention to the skills of judgment and verification, which matter more as the tools become more fluent.',
        'opener' => [
            'title' => 'Teachable is a decision',
            'dek' => 'Skill with these tools is built, and someone has to budget for building it.',
            'body' => 'Handing people a tool is not the same as teaching them to use it well. Organizations that see lasting gains invest in practice, feedback, and the confidence to say when the system is wrong.',
            'questions' => [
                'How many hours of practice did staff get before results were measured?',
                'Do people feel safe reporting that the tool made a mistake?',
                'Which skills are being built, and which are being allowed to fade?',
            ],
        ],
    ],
    [
        'slug' => 'rules-of-the-road',
        'name' => 'Rules of the Road',
        'tagline' => 'Regulation, standards, and compliance across jurisdictions.',
        'mission' => 'The rules governing AI differ by country, by sector, and increasingly by use. This department tracks legislation, standards, and regulatory guidance, and translates them into what an organization has to do. We cite the primary text, separate what is in force from what is proposed, and note where reasonable lawyers disagree. Nothing here is legal advice; it is a map to help readers ask their own counsel better questions.',
        'opener' => [
            'title' => 'Read the actual rule',
            'dek' => 'Our approach to regulation: primary sources, plain language, clear dates.',
            'body' => 'Compliance coverage often passes along a summary of a summary. We will go back to the text, say when it takes effect and whom it binds, and distinguish an obligation from a recommendation.',
            'questions' => [
                'Is this rule in force, pending, or only proposed?',
                'Which organizations and which uses does it actually cover?',
                'What evidence would a regulator expect to see?',
            ],
        ],
    ],
    [
        'slug' => 'trust-and-safety',
        'name' => 'Trust and Safety',
        'tagline' => 'Security, privacy, data sovereignty, and adversarial risks.',
        'mission' => 'AI systems widen the attack surface and concentrate sensitive data. This department covers the defensive side: protecting the data that goes into and comes out of models, keeping it within the borders and systems where it belongs, and understanding how these systems are manipulated, from poisoned inputs to instructions hidden in documents. The aim is practical guidance for people responsible for keeping a deployment safe.',
        'opener' => [
            'title' => 'Assume someone is trying',
            'dek' => 'Security for AI systems begins with the same habits as security for anything else.',
            'body' => 'A model that reads untrusted content can be steered by it. A system that holds sensitive data is a target. Good practice starts with knowing what the system can reach and limiting it to what the task requires.',
            'questions' => [
                'What data can this system read, and what can it act on?',
                'Where does the data physically reside, and under whose law?',
                'What happens when the system is fed content written to mislead it?',
            ],
        ],
    ],
    [
        'slug' => 'open-bench',
        'name' => 'Open Bench',
        'tagline' => 'Open-source models and tools, with independent benchmarks on modest hardware.',
        'mission' => 'Open models and tools let an organization inspect, modify, and run what it depends on. This department tests them independently, on hardware a small organization could afford, and publishes the method alongside the result so anyone can repeat it. We cover licenses as carefully as performance, because a model that is free to download is not always free to use the way a business needs.',
        'opener' => [
            'title' => 'Tested here, repeatable there',
            'dek' => 'Every benchmark we publish will come with the means to rerun it.',
            'body' => 'Vendor benchmarks are run on vendor hardware under vendor conditions. Our bench is deliberately ordinary, and the published method matters as much as the score, since a result is only useful if a reader can check it.',
            'questions' => [
                'What exactly was run, on what machine, with what settings?',
                'What does the license permit a business to do?',
                'How does the result change on the tasks readers actually have?',
            ],
        ],
    ],
    [
        'slug' => 'the-corner-office',
        'name' => 'The Corner Office',
        'tagline' => 'Interviews with leaders on strategy, governance, and decisions they would reverse.',
        'mission' => 'Strategy is easier to describe in advance than in hindsight. This department interviews the people who made the decisions: executives, founders, public officials, and board members. We ask how they set direction, how they govern what they deployed, and which choices they would make differently now. The conversations are edited for length and clarity and never for flattery.',
        'opener' => [
            'title' => 'The question we always ask',
            'dek' => 'What would you reverse? The answer tells a reader more than any roadmap.',
            'body' => 'Leaders are practiced at describing plans. They are more useful when describing mistakes. Every interview in this department will include the decision the subject would take back, and why.',
            'questions' => [
                'Who in the organization can say no to an AI deployment?',
                'What did you believe two years ago that you no longer believe?',
                'Which decision would you reverse, and what did it cost?',
            ],
        ],
    ],
    [
        'slug' => 'sector-watch',
        'name' => 'Sector Watch',
        'tagline' => 'A rotating industry focus: healthcare, manufacturing, finance, education, the public sector.',
        'mission' => 'The same technology behaves differently in a hospital, a factory, a bank, a school, and a government office, because the stakes, the data, and the rules all differ. This department rotates through industries, looking at what is in real use, what the sector\'s constraints demand, and what one industry has learned that another could borrow.',
        'opener' => [
            'title' => 'Context decides',
            'dek' => 'Why we will cover AI one sector at a time.',
            'body' => 'General advice about AI breaks down on contact with a specific industry. A tolerable error rate in marketing copy is intolerable in a medication order. Each rotation of this department starts from what the sector cannot afford to get wrong.',
            'questions' => [
                'What is the cost of an error in this sector, and who pays it?',
                'Which uses are in daily operation and which are still pilots?',
                'What has this industry learned that others have not yet heard?',
            ],
        ],
    ],
    [
        'slug' => 'agents-at-work',
        'name' => 'Agents at Work',
        'tagline' => 'Autonomous and workflow AI: where it helps, where it breaks, how to supervise it.',
        'mission' => 'Systems that take actions, and not only produce text, raise the stakes of every other topic in this magazine. This department covers agents and automated workflows in practice: the tasks they complete reliably, the ways they fail, and the supervision that keeps a person in command. We focus on permissions, checkpoints, and the ability to stop and undo, since those determine whether autonomy is an asset or a liability.',
        'opener' => [
            'title' => 'Who is supervising?',
            'dek' => 'An agent is only as safe as the limits and checkpoints around it.',
            'body' => 'Delegating work to software that can act on its own is a management problem as much as a technical one. The questions are familiar: what is it allowed to do, when must it ask, and how is its work reviewed.',
            'questions' => [
                'What can the agent do without asking a person first?',
                'How is its work checked, and how often?',
                'Can its actions be stopped and undone?',
            ],
        ],
    ],
    [
        'slug' => 'buyers-brief',
        'name' => 'Buyer\'s Brief',
        'tagline' => 'Procurement guidance, vendor scorecards, and build-versus-buy analysis.',
        'mission' => 'Buying AI well means asking better questions than the sales deck answers. This department is the magazine\'s signature feature: procurement guidance, build-versus-buy analysis, and a recurring scorecard that rates products against the principles set out in our core departments. Is it clean, pro-human, lean on compute, small in footprint, able to run locally, verifiable, and auditable? Scores come with the reasoning behind them, so readers can weigh the criteria for themselves.',
        'opener' => [
            'title' => 'How the scorecard works',
            'dek' => 'Seven principles, one consistent scale, and the reasoning shown every time.',
            'body' => 'Each Buyer\'s Brief scorecard rates a product from 0 to 5 on the seven principles covered by departments two through eight. A score is an editorial judgment, and each one is published with the evidence behind it. The blank card below shows the criteria.',
            'questions' => [
                'Does the product meet the need with the least compute, storage, and energy?',
                'Can it run locally, and can its results be verified and audited?',
                'Does it extend the people using it, or is it sold as a way to remove them?',
            ],
            'scorecard' => true,
        ],
    ],
];

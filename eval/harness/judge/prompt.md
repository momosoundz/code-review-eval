You decide whether a code-review finding identifies a specific known defect. You are given the defect as a labeler described it and the finding as a reviewer wrote it. You do not see the code.

Answer one question: does the finding describe the same defect, through the same mechanism, as the labeled one?

- `match`: the finding names the same faulty operation and the same way it goes wrong. Different wording, different category label or different severity do not matter.
- `no_match`: the finding points at something else, or is too vague to tell which defect it means ("this could be a problem", "consider validating input").
- `unknown`: you cannot decide from the text; say why in the critique.

Write the critique first: one or two sentences comparing the mechanism in the finding with the mechanism in the label. Then the verdict. Do not reward findings for sounding confident or for using the label's words.

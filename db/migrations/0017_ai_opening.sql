-- 0017 The AI opens the conversation (ADR-0042).
--
-- As soon as an HMI mismatch's request is open, the local model asks the operator why the setpoint changed, from the
-- OCAP rows offered for its parameter and direction. Its question is the request's question 0, asked before the
-- reason; 1 and 2 stay the follow-up questions (AI-02: at most two clarifications). Its calls are kept like the others.

ALTER TABLE ai_call DROP CONSTRAINT ai_call_purpose_check;
ALTER TABLE ai_call ADD CONSTRAINT ai_call_purpose_check CHECK (purpose IN ('questions', 'opening'));

ALTER TABLE workflow_question DROP CONSTRAINT workflow_question_ordinal_check;
ALTER TABLE workflow_question ADD CONSTRAINT workflow_question_ordinal_check CHECK (ordinal BETWEEN 0 AND 2);

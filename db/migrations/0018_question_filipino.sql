-- 0018 The AI's questions in Filipino too (LAN-01, ADR-0043).
--
-- The operator's chat opens in Tagalog. The local model writes each question in English and in Filipino at once, so
-- switching languages is instant; the English stays the record's language (answers keep it, Managers read it). A
-- Filipino text that breaks the rules is left out and the English is shown instead.

ALTER TABLE workflow_question ADD COLUMN question_fil text CHECK (question_fil IS NULL OR btrim(question_fil) <> '');

import json

from app import ncr


class Words:
    """A model that answers from a list; records what it was sent."""
    mode, model = "LIVE", "fake"

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def chat(self, messages, tools, response_format=None):
        self.seen.append(messages)
        return {"message": {"role": "assistant", "content": json.dumps({"claims": self.answers.pop(0)})}}


CLAIMS = [{"claim_id": "C1", "classification": "OBSERVED", "text": "Lot L02 has 25 AOI FAIL of 47."},
          {"claim_id": "C2", "classification": "CALCULATED", "text": "Mean SPI volume is 0.1128 mm3."},
          {"claim_id": "C3", "classification": "UNKNOWN", "text": "Board L02-P11/B3 has no AOI record."}]


def test_the_ai_writes_each_sentence_and_a_wrong_number_goes_back_until_fixed_or_kept_as_facts():
    p = Words([{"claim_id": "C1", "text": "LOT L02는 AOI 47건 중 25건이 불합격입니다."},
               {"claim_id": "C2", "text": "SPI 평균 체적은 0.113 mm3입니다."},  # rounded: refused
               {"claim_id": "C3", "text": "보드 L02-P11/B3에는 AOI 기록이 없습니다."}],
              [{"claim_id": "C2", "text": "SPI 평균 체적은 0.1128 mm3입니다."}])
    out, builder = ncr.ai_wording(p, "NCR", CLAIMS)
    assert [c["text"] for c in out] == ["LOT L02는 AOI 47건 중 25건이 불합격입니다.", "SPI 평균 체적은 0.1128 mm3입니다.",
                                        "보드 L02-P11/B3에는 AOI 기록이 없습니다."]
    assert builder == "TEMPLATE_AI_WORDING:fake" and len(p.seen) == 2
    assert "0.1128" in p.seen[1][-1]["content"] and "C2" in p.seen[1][-1]["content"]  # the reason went back

    never = Words(*[[{"claim_id": "C2", "text": "평균 체적 약 0.11"}]] * 3)
    out, _ = ncr.ai_wording(never, "NCR", CLAIMS[1:2])
    assert out == CLAIMS[1:2]  # still wrong after the repairs: the facts sentence stays

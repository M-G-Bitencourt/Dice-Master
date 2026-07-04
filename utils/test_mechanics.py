from utils.dice_mechanics import consume_deterministic_fate
from utils.dice_mechanics import hdm_dices
from random import randint


def quick_dispute(player_id: int, effective_nh1: int, effective_nh2: int):
    # Deterministic Device Block
    fate = consume_deterministic_fate(player_id)

    if fate is not None:

        if fate == 0:  # Both pass, you win by the margin of success
            loop_count = 0
            while True:
                dices1 = hdm_dices(effective_nh1, 0)
                dices2 = hdm_dices(effective_nh2, 0)
                if (effective_nh1 - sum(dices1)) > (effective_nh2 - sum(dices2)):
                    break
                loop_count += 1

                if loop_count > 100:
                    dices2 = hdm_dices(effective_nh2, 1)
                    break

        elif fate == 1:  # Both pass, you lose by the margin of success
            loop_count = 0
            while True:
                dices1 = hdm_dices(effective_nh1, 0)
                dices2 = hdm_dices(effective_nh2, 0)
                if (effective_nh1 - sum(dices1)) < (effective_nh2 - sum(dices2)):
                    break
                loop_count += 1

                if loop_count > 100:
                    dices1 = hdm_dices(effective_nh1, 1)
                    break

        elif fate == 2:  # You pass, the enemy fails.
            dices1 = hdm_dices(effective_nh1, 0)
            dices2 = hdm_dices(effective_nh2, 1)

        elif fate == 3:  # You fail, the enemy passes.
            dices1 = hdm_dices(effective_nh1, 1)
            dices2 = hdm_dices(effective_nh2, 0)

    else:
        dices1 = [randint(1, 6) for _ in range(3)]
        dices2 = [randint(1, 6) for _ in range(3)]

    dice_pool1 = sum(dices1)
    success_roll1 = False if dice_pool1 > effective_nh1 else True
    margin1 = effective_nh1 - dice_pool1

    dice_pool2 = sum(dices2)
    success_roll2 = False if dice_pool2 > effective_nh2 else True
    margin2 = effective_nh2 - dice_pool2

    total_result = {
        "result1": {
            "dice_pool1": dice_pool1,
            "success_roll1": success_roll1,
            "margin1": margin1,
            "dices1": dices1
        },
        "result2": {
            "dice_pool2": dice_pool2,
            "success_roll2": success_roll2,
            "margin2": margin2,
            "dices2": dices2
        },
    }

    return total_result
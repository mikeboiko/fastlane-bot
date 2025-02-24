# coding=utf-8
"""
Main integration point for the bot optimizer and other infrastructure.

(c) Copyright Bprotocol foundation 2023.
Licensed under MIT

                      ,(&@(,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
               ,%@@@@@@@@@@,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,.
          @@@@@@@@@@@@@@@@@&,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,.
          @@@@@@@@@@@@@@@@@@/,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
          @@@@@@@@@@@@@@@@@@@,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
          @@@@@@@@@@@@@@@@@@@%,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
          @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@.
          @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@.
      (((((((((&@@@@@@@@@@@@@@@@@@@@@@@@@@@(,,,,,,,%@@@@@,
      (((((((((@@@@@@@@@@@@@@@@@@@@@@@@@@((((,,,,,,,#@@.
     ,((((((((#@@@@@@@@@@@/////////////((((((/,,,,,,,,
     *((((((((#@@@@@@@@@@@#,,,,,,,,,,,,/((((((/,,,,,,,,
     /((((((((#@@@@@@@@@@@@*,,,,,,,,,,,,(((((((*,,,,,,,,
     (((((((((%@@@@@@@@@@@@&,,,,,,,,,,,,/(((((((,,,,,,,,,.
    .(((((((((&@@@@@@@@@@@@@/,,,,,,,,,,,,((((((((,,,,,,,,,,
    *(((((((((@@@@@@@@@@@@@@@,,,,,,,,,,,,*((((((((,,,,,,,,,,
    /((((((((#@@@@@@@@@@@@@@@@/,,,,,,,,,,,((((((((/,,,,,,,,,,.
    (((((((((%@@@@@@@@@@@@@@@@@(,,,,,,,,,,*((((((((/,,,,,,,,,,,
    (((((((((%@@@@@@@@@@@@@@@@@@%,,,,,,,,,,(((((((((*,,,,,,,,,,,
    ,(((((((((&@@@@@@@@@@@@@@@@@@@&,,,,,,,,,*(((((((((*,,,,,,,,,,,.
    ((((((((((@@@@@@@@@@@@@@@@@@@@@@*,,,,,,,,((((((((((,,,,,,,,,,,,,
    ((((((((((@@@@@@@@@@@@@@@@@@@@@@@(,,,,,,,*((((((((((,,,,,,,,,,,,,
    (((((((((#@@@@@@@@@@@@&#(((((((((/,,,,,,,,/((((((((((,,,,,,,,,,,,,
    %@@@@@@@@@@@@@@@@@@((((((((((((((/,,,,,,,,*(((((((#&@@@@@@@@@@@@@.
    &@@@@@@@@@@@@@@@@@@#((((((((((((*,,,,,,,,,/((((%@@@@@@@@@@@@@%
     &@@@@@@@@@@@@@@@@@@%(((((((((((*,,,,,,,,,*(#@@@@@@@@@@@@@@*
     /@@@@@@@@@@@@@@@@@@@%((((((((((*,,,,,,,,,,,,,,,,,,,,,,,,,
     %@@@@@@@@@@@@@@@@@@@@&(((((((((*,,,,,,,,,,,,,,,,,,,,,,,,,,
     @@@@@@@@@@@@@@@@@@@@@@@((((((((,,,,,,,,,,,,,,,,,,,,,,,,,,,,
    ,@@@@@@@@@@@@@@@@@@@@@@@@#((((((,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
    #@@@@@@@@@@@@@@@@@@@@@@@@@#(((((,,,,,,,,,,,,,,,,,,,,,,,,,,,,,.
    &@@@@@@@@@@@@@@@@@@@@@@@@@@%((((,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
    @@@@@@@@@@@@@@@@@@@@@@@@@@@@&(((,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
    (@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@((,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,

"""
__VERSION__ = "3-b2.2"
__DATE__ = "20/June/2023"

import random
import time
import json
from _decimal import Decimal
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Generator, List, Dict, Tuple, Any, Callable
from typing import Optional

from web3 import Web3

import fastlane_bot
from fastlane_bot.config import Config
from fastlane_bot.helpers import (
    TxRouteHandler,
    TxHelpers,
    TxHelpersBase,
    TradeInstruction,
    Univ3Calculator,
    add_wrap_or_unwrap_trades_to_route,
    split_carbon_trades,
    submit_transaction_tenderly
)
from fastlane_bot.helpers.routehandler import maximize_last_trade_per_tkn
from fastlane_bot.tools.cpc import ConstantProductCurve as CPC, CPCContainer, T
from fastlane_bot.tools.optimizer import CPCArbOptimizer
from .config.constants import FLASHLOAN_FEE_MAP
from .events.interface import QueryInterface
from .modes.pairwise_multi import FindArbitrageMultiPairwise
from .modes.pairwise_multi_all import FindArbitrageMultiPairwiseAll
from .modes.pairwise_multi_pol import FindArbitrageMultiPairwisePol
from .modes.pairwise_single import FindArbitrageSinglePairwise
from .modes.triangle_multi import ArbitrageFinderTriangleMulti
from .modes.triangle_single import ArbitrageFinderTriangleSingle
from .modes.triangle_bancor_v3_two_hop import ArbitrageFinderTriangleBancor3TwoHop
from .utils import num_format, log_format, num_format_float


@dataclass
class CarbonBotBase:
    """
    Base class for the business logic of the bot.

    Attributes
    ----------
    db: DatabaseManager
        the database manager.
    TxRouteHandlerClass
        ditto (default: TxRouteHandler).
    TxHelpersClass: class derived from TxHelpersBase
        ditto (default: TxHelpers).

    """

    __VERSION__ = __VERSION__
    __DATE__ = __DATE__

    db: QueryInterface = field(init=False)
    TxRouteHandlerClass: any = None
    TxHelpersClass: any = None
    ConfigObj: Config = None
    usd_gas_limit: int = 150
    min_profit: int = 60
    polling_interval: int = None

    def __post_init__(self):
        """
        The post init method.
        """

        if self.ConfigObj is None:
            self.ConfigObj = Config()

        self.c = self.ConfigObj

        assert (
            self.polling_interval is None
        ), "polling_interval is now a parameter to run"

        if self.TxRouteHandlerClass is None:
            self.TxRouteHandlerClass = TxRouteHandler

        if self.TxHelpersClass is None:
            self.TxHelpersClass = TxHelpers(ConfigObj=self.ConfigObj)
        assert issubclass(
            self.TxHelpersClass.__class__, TxHelpersBase
        ), f"TxHelpersClass not derived from TxHelpersBase {self.TxHelpersClass}"

        self.db = QueryInterface(ConfigObj=self.ConfigObj)
        self.RUN_FLASHLOAN_TOKENS = [*self.ConfigObj.CHAIN_FLASHLOAN_TOKENS.values()]

    @property
    def C(self) -> Any:
        """
        Convenience method self.ConfigObj
        """
        return self.ConfigObj

    @staticmethod
    def versions():
        """
        Returns the versions of the module and its Carbon dependencies.
        """
        s = [f"fastlane_bot v{__VERSION__} ({__DATE__})"]
        s += ["carbon v{0.__VERSION__} ({0.__DATE__})".format(CPC)]
        s += ["carbon v{0.__VERSION__} ({0.__DATE__})".format(CPCArbOptimizer)]
        return s

    UDTYPE_FROM_CONTRACTS = "from_contracts"
    UDTYPE_FROM_EVENTS = "from_events"

    def get_curves(self) -> CPCContainer:
        """
        Gets the curves from the database.

        Returns
        -------
        CPCContainer
            The container of curves.
        """
        self.db.refresh_pool_data()
        pools_and_tokens = self.db.get_pool_data_with_tokens()
        curves = []
        tokens = self.db.get_tokens()
        ADDRDEC = {t.address: (t.address, int(t.decimals)) for t in tokens}

        for p in pools_and_tokens:
            try:
                p.ADDRDEC = ADDRDEC
                curves += p.to_cpc()
            except NotImplementedError as e:
                # Currently not supporting Solidly V2 Stable pools. This will be removed when support is added, but for now the error message is suppressed.
                if "Stable Solidly V2" in str(e):
                    continue
                else:
                    self.ConfigObj.logger.error(
                        f"[bot.get_curves] Pool type not yet supported, error: {e}\n"
                    )
            except ZeroDivisionError as e:
                self.ConfigObj.logger.error(
                    f"[bot.get_curves] MUST FIX INVALID CURVE {p} [{e}]\n"
                )
            except CPC.CPCValidationError as e:
                self.ConfigObj.logger.error(
                    f"[bot.get_curves] MUST FIX INVALID CURVE {p} [{e}]\n"
                )
            except TypeError as e:
                if fastlane_bot.__version__ not in ["3.0.31", "3.0.32"]:
                    self.ConfigObj.logger.error(
                        f"[bot.get_curves] MUST FIX DECIMAL ERROR CURVE {p} [{e}]\n"
                    )
            except p.DoubleInvalidCurveError as e:
                self.ConfigObj.logger.error(
                    f"[bot.get_curves] MUST FIX DOUBLE INVALID CURVE {p} [{e}]\n"
                )
            except Univ3Calculator.DecimalsMissingError as e:
                self.ConfigObj.logger.error(
                    f"[bot.get_curves] MUST FIX DECIMALS MISSING [{e}]\n"
                )
            except Exception as e:
                self.ConfigObj.logger.error(
                    f"[bot.get_curves] error converting pool to curve {p}\n[ERR={e}]\n\n"
                )

        return CPCContainer(curves)


@dataclass
class CarbonBot(CarbonBotBase):
    """
    A class that handles the business logic of the bot.

    MAIN ENTRY POINTS
    :run:               Runs the bot.
    """

    AM_REGULAR = "regular"
    AM_SINGLE = "single"
    AM_TRIANGLE = "triangle"
    AM_MULTI = "multi"
    AM_MULTI_TRIANGLE = "multi_triangle"
    AM_BANCOR_V3 = "bancor_v3"
    RUN_SINGLE = "single"
    RUN_CONTINUOUS = "continuous"
    RUN_POLLING_INTERVAL = 60  # default polling interval in seconds
    SCALING_FACTOR = 0.999
    AO_TOKENS = "tokens"
    AO_CANDIDATES = "candidates"
    BNT_ETH_CID = "0xc4771395e1389e2e3a12ec22efbb7aff5b1c04e5ce9c7596a82e9dc8fdec725b"

    def __post_init__(self):
        super().__post_init__()

    class NoArbAvailable(Exception):
        pass

    def _simple_ordering_by_src_token(
        self, best_trade_instructions_dic, best_src_token
    ):
        """
        Reorders a trade_instructions_dct so that all items where the best_src_token is the tknin are before others
        """
        if best_trade_instructions_dic is None:
            raise self.NoArbAvailable(
                f"[_simple_ordering_by_src_token] {best_trade_instructions_dic}"
            )
        src_token_instr = [
            x for x in best_trade_instructions_dic if x["tknin"] == best_src_token
        ]
        non_src_token_instr = [
            x
            for x in best_trade_instructions_dic
            if (x["tknin"] != best_src_token and x["tknout"] != best_src_token)
        ]
        src_token_end = [
            x for x in best_trade_instructions_dic if x["tknout"] == best_src_token
        ]
        ordered_trade_instructions_dct = (
            src_token_instr + non_src_token_instr + src_token_end
        )

        tx_in_count = len(src_token_instr)
        return ordered_trade_instructions_dct, tx_in_count

    def _simple_ordering_by_src_token_v2(
        self, best_trade_instructions_dic, best_src_token
    ):
        """
        Reorders a trade_instructions_dct so that all items where the best_src_token is the tknin are before others
        """
        if best_trade_instructions_dic is None:
            raise self.NoArbAvailable(
                f"[_simple_ordering_by_src_token] {best_trade_instructions_dic}"
            )
        trades = [
            x for x in best_trade_instructions_dic if x["tknin"] == best_src_token
        ]
        tx_in_count = len(trades)
        while len(trades) < len(best_trade_instructions_dic):
            next_tkn = trades[-1]["tknout"]
            trades += [x for x in best_trade_instructions_dic if x["tknin"] == next_tkn]

        return trades, tx_in_count

    def _basic_scaling(self, best_trade_instructions_dic, best_src_token):
        """
        For items in the trade_instruction_dic scale the amtin by 0.999 if its the src_token
        """
        scaled_best_trade_instructions_dic = [
            dict(x.items()) for x in best_trade_instructions_dic
        ]
        for item in scaled_best_trade_instructions_dic:
            if item["tknin"] == best_src_token:
                item["amtin"] *= self.SCALING_FACTOR

        return scaled_best_trade_instructions_dic

    def _convert_trade_instructions(
        self, trade_instructions_dic: List[Dict[str, Any]]
    ) -> List[TradeInstruction]:
        """
        Converts the trade instructions dictionaries into `TradeInstruction` objects.

        Parameters
        ----------
        trade_instructions_dic: List[Dict[str, Any]]
            The trade instructions dictionaries.

        Returns
        -------
        List[Dict[str, Any]]
            The trade instructions.
        """
        errorless_trade_instructions_dicts = [
            {k: v for k, v in trade_instructions_dic[i].items() if k != "error"}
            for i in range(len(trade_instructions_dic))
        ]
        result = (
            {
                **ti,
                "raw_txs": "[]",
                "pair_sorting": "",
                "ConfigObj": self.ConfigObj,
                "db": self.db,
            }
            for ti in errorless_trade_instructions_dicts
            if ti is not None
        )
        result = self._add_strategy_id_to_trade_instructions_dic(result)
        result = [TradeInstruction(**ti) for ti in result]
        return result

    def _add_strategy_id_to_trade_instructions_dic(
        self, trade_instructions_dic: Generator
    ) -> List[Dict[str, Any]]:
        lst = []
        for ti in trade_instructions_dic:
            cid = ti["cid"].split('-')[0]
            ti["strategy_id"] = self.db.get_pool(
                cid=cid
            ).strategy_id
            lst.append(ti)
        return lst

    @staticmethod
    def _check_if_carbon(cid: str):
        """
        Checks if the curve is a Carbon curve.

        Returns
        -------
        bool
            Whether the curve is a Carbon curve.
        """

        if "-" in cid:
            cid_tkn = cid.split("-")[1]
            cid = cid.split("-")[0]
            return True, cid_tkn, cid
        return False, "", cid

    @staticmethod
    def _check_if_not_carbon(cid: str):
        """
        Checks if the curve is a Carbon curve.
        Returns
        -------
        bool
            Whether the curve is a Carbon curve.
        """
        return "-" not in cid

    @dataclass
    class ArbCandidate:
        """
        The arbitrage candidates.
        """

        result: any
        constains_carbon: bool = None
        best_profit_usd: float = None

        @property
        def r(self):
            return self.result

    def _get_deadline(self, block_number) -> int:
        """
        Gets the deadline for a transaction.

        Returns
        -------
        int
            The deadline (as UNIX epoch).
        """
        block_number = (
            self.ConfigObj.w3.eth.block_number if block_number is None else block_number
        )
        return (
            self.ConfigObj.w3.eth.get_block(block_number).timestamp
            + self.ConfigObj.DEFAULT_BLOCKTIME_DEVIATION
        )

    @staticmethod
    def _get_arb_finder(arb_mode: str) -> Callable:
        if arb_mode in {"single", "pairwise_single"}:
            return FindArbitrageSinglePairwise
        elif arb_mode in {"multi", "pairwise_multi"}:
            return FindArbitrageMultiPairwise
        elif arb_mode in {"triangle", "triangle_single"}:
            return ArbitrageFinderTriangleSingle
        elif arb_mode in {"multi_triangle", "triangle_multi"}:
            return ArbitrageFinderTriangleMulti
        elif arb_mode in {"b3_two_hop"}:
            return ArbitrageFinderTriangleBancor3TwoHop
        elif arb_mode in {"multi_pairwise_pol"}:
            return FindArbitrageMultiPairwisePol
        elif arb_mode in {"multi_pairwise_all"}:
            return FindArbitrageMultiPairwiseAll

    def _find_arbitrage(
        self,
        flashloan_tokens: List[str],
        CCm: CPCContainer,
        arb_mode: str = None,
        randomizer=int
    ) -> dict:
        random_mode = self.AO_CANDIDATES if randomizer else None
        arb_mode = self.AM_SINGLE if arb_mode is None else arb_mode
        arb_finder = self._get_arb_finder(arb_mode)
        finder = arb_finder(
            flashloan_tokens=flashloan_tokens,
            CCm=CCm,
            mode="bothin",
            result=random_mode,
            ConfigObj=self.ConfigObj,
        )
        return {"finder": finder, "r": finder.find_arbitrage()}

    def _run(
        self,
        flashloan_tokens: List[str],
        CCm: CPCContainer,
        *,
        arb_mode: str = None,
        randomizer=int,
        data_validator=True,
        replay_mode: bool = False,
    ) -> Any:
        """
        Runs the bot.

        Parameters
        ----------
        flashloan_tokens: List[str]
            The tokens to flashloan.
        CCm: CPCContainer
            The container.
        arb_mode: str
            The arbitrage mode.
        randomizer: int
            randomizer (int): The number of arb opportunities to randomly pick from, sorted by expected profit.
        data_validator: bool
            If extra data validation should be performed

        Returns
        -------
        Transaction hash.

        """
        arbitrage = self._find_arbitrage(flashloan_tokens=flashloan_tokens, CCm=CCm, arb_mode=arb_mode, randomizer=randomizer)
        finder, r = [arbitrage[key] for key in ["finder", "r"]]

        if r is None or len(r) == 0:
            self.ConfigObj.logger.info("[bot._run] No eligible arb opportunities.")
            return None

        self.ConfigObj.logger.info(
            f"[bot._run] Found {len(r)} eligible arb opportunities."
        )
        r = self.randomize(arb_opps=r, randomizer=randomizer)

        if data_validator:
            # Add random chance if we should check or not
            r = self.validate_optimizer_trades(
                arb_opp=r, arb_mode=arb_mode, arb_finder=finder
            )
            if r is None:
                self.ConfigObj.logger.warning(
                    "[bot._run] Math validation eliminated arb opportunity, restarting."
                )
                return None
            if replay_mode:
                pass
            elif self.validate_pool_data(arb_opp=r):
                self.ConfigObj.logger.debug(
                    "[bot._run] All data checks passed! Pools in sync!"
                )
            else:
                self.ConfigObj.logger.warning(
                    "[bot._run] Data validation failed. Updating pools and restarting."
                )
                return None

        return self._handle_trade_instructions(CCm, arb_mode, r)

    def validate_optimizer_trades(self, arb_opp, arb_mode, arb_finder):
        """
        Validates arbitrage trade input using equations that account for fees.
        This has limited coverage, but is very effective for the instances it covers.

        Parameters
        ----------
        arb_opp: tuple
            The tuple containing an arbitrage opportunity found by the Optimizer
        arb_mode: str
            The arbitrage mode.
        arb_finder: Any
            The Arb mode class that handles the differences required for each arb route.


        Returns
        -------
        tuple or None
        """

        if arb_mode == "bancor_v3" or arb_mode == "b3_two_hop":
            (
                best_profit,
                best_trade_instructions_df,
                best_trade_instructions_dic,
                best_src_token,
                best_trade_instructions,
            ) = arb_opp

            (
                ordered_trade_instructions_dct,
                tx_in_count,
            ) = self._simple_ordering_by_src_token(
                best_trade_instructions_dic, best_src_token
            )
            cids = []
            for pool in ordered_trade_instructions_dct:
                pool_cid = pool["cid"]
                if "-0" in pool_cid or "-1" in pool_cid:
                    self.ConfigObj.logger.debug(
                        f"[bot.validate_optimizer_trades] Math arb validation not currently supported for arbs with "
                        f"Carbon, returning to main flow."
                    )
                    return arb_opp
                cids.append(pool_cid)
            if len(cids) > 3:
                self.ConfigObj.logger.warning(
                    f"[bot.validate_optimizer_trades] Math validation not supported for more than 3 pools, returning "
                    f"to main flow."
                )
                return arb_opp
            max_trade_in = arb_finder.get_optimal_arb_trade_amts(
                cids=cids, flt=best_src_token
            )
            if max_trade_in is None:
                return None
            if type(max_trade_in) != float and type(max_trade_in) != int:
                return None
            if max_trade_in < 0.0:
                return None
            self.ConfigObj.logger.debug(
                f"[bot.validate_optimizer_trades] max_trade_in equation = {max_trade_in}, optimizer trade in = {ordered_trade_instructions_dct[0]['amtin']}"
            )
            ordered_trade_instructions_dct[0]["amtin"] = max_trade_in

            best_trade_instructions_dic = ordered_trade_instructions_dct
        else:
            return arb_opp

        arb_opp = (
            best_profit,
            best_trade_instructions_df,
            best_trade_instructions_dic,
            best_src_token,
            best_trade_instructions,
        )
        return arb_opp

    def validate_pool_data(self, arb_opp):
        """
        Validates that the data for each pool in the arbitrage opportunity is fresh.

        Parameters
        ----------
        arb_opp: tuple
            The tuple containing an arbitrage opportunity found by the Optimizer

        Returns
        -------
        bool
        """
        self.ConfigObj.logger.info("[bot.validate_pool_data] Validating pool data...")
        (
            best_profit,
            best_trade_instructions_df,
            best_trade_instructions_dic,
            best_src_token,
            best_trade_instructions,
        ) = arb_opp
        for pool in best_trade_instructions_dic:
            pool_cid = pool["cid"].split("-")[0]
            strategy_id = pool["strategy_id"]
            current_pool = self.db.get_pool(cid=pool_cid)
            pool_info = {
                "cid": pool_cid,
                "strategy_id": strategy_id,
                "id": current_pool.id,
                "address": current_pool.address,
                "pair_name": current_pool.pair_name,
                "exchange_name": current_pool.exchange_name,
                "tkn0_address": current_pool.tkn0_address,
                "tkn1_address": current_pool.tkn1_address,
                "tkn0_symbol": current_pool.tkn0_symbol,
                "tkn1_symbol": current_pool.tkn1_symbol,
                "tkn0_decimals" : current_pool.tkn0_decimals,
                "tkn1_decimals": current_pool.tkn1_decimals,
            }

            fetched_pool = self.db.mgr.update_from_pool_info(pool_info=pool_info)
            if fetched_pool is None:
                self.ConfigObj.logger.error(
                    f"[bot.validate_pool_data] Could not fetch pool data for {pool_cid}"
                )

            ex_name = fetched_pool["exchange_name"]
            self._validate_pool_data_logging(pool_cid, fetched_pool)

            if ex_name == "bancor_v3":
                self._validate_pool_data_logging(pool_cid, fetched_pool)

            if current_pool.exchange_name in self.ConfigObj.CARBON_V1_FORKS:
                if (
                    current_pool.y_0 != fetched_pool["y_0"]
                    or current_pool.y_1 != fetched_pool["y_1"]
                ):
                    self.ConfigObj.logger.debug(
                        "[bot.validate_pool_data] Carbon pool not up to date, updating and restarting."
                    )
                    return False
            elif current_pool.exchange_name in [
                "balancer",
            ]:
                for idx, balance in enumerate(current_pool.token_balances):
                    if balance != fetched_pool[f"tkn{idx}_balance"]:
                        self.ConfigObj.logger.debug(
                            "[bot.validate_pool_data] Balancer pool not up to date, updating and restarting."
                        )
                        return False
            elif current_pool.exchange_name in self.ConfigObj.UNI_V3_FORKS:
                if (
                    current_pool.liquidity != fetched_pool["liquidity"]
                    or current_pool.sqrt_price_q96 != fetched_pool["sqrt_price_q96"]
                    or current_pool.tick != fetched_pool["tick"]
                ):
                    self.ConfigObj.logger.debug(
                        "[bot.validate_pool_data] UniV3 pool not up to date, updating and restarting."
                    )
                    return False

            elif (
                current_pool.tkn0_balance != fetched_pool["tkn0_balance"]
                or current_pool.tkn1_balance != fetched_pool["tkn1_balance"]
            ):
                self.ConfigObj.logger.debug(
                    f"[bot.validate_pool_data] {ex_name} pool not up to date, updating and restarting."
                )
                return False

        return True

    @staticmethod
    def randomize(arb_opps, randomizer: int = 1):
        """
        Sorts arb opportunities by profit, then returns a random element from the top N arbs, with N being the value input in randomizer.
        :param arb_opps: Arb opportunities
        :param randomizer: the number of arb ops to choose from after sorting by profit. For example, a value of 3 would be the top 3 arbs by profitability.
        returns:
            A randomly selected arb opportunity.

        """
        if arb_opps is None:
            return None
        if len(arb_opps) > 0:
            arb_opps.sort(key=lambda x: x[0], reverse=True)
            if randomizer < 1:
                randomizer = 1
            if len(arb_opps) < randomizer:
                randomizer = len(arb_opps)
            top_n_arbs = arb_opps[:randomizer]
            return random.choice(top_n_arbs)
        else:
            return None

    def _validate_pool_data_logging(
        self, pool_cid: str, fetched_pool: Dict[str, Any]
    ) -> None:
        """
        Logs the pool data validation.

        Parameters
        ----------
        pool_cid: str
            The pool CID.
        fetched_pool: dict
            The fetched pool data.

        """
        self.ConfigObj.logger.debug(f"[bot.py validate] pool_cid: {pool_cid}")
        self.ConfigObj.logger.debug(
            f"[bot.py validate] fetched_pool: {fetched_pool['exchange_name']}"
        )
        self.ConfigObj.logger.debug(f"[bot.py validate] fetched_pool: {fetched_pool}")

    @staticmethod
    def _carbon_in_trade_route(trade_instructions: List[TradeInstruction]) -> bool:
        """
        Returns True if the exchange route includes Carbon
        """
        return any(trade.is_carbon for trade in trade_instructions)
    
    def get_prices_simple(self, CCm, tkn0, tkn1):
        curve_prices = [(x.params['exchange'],x.descr,x.cid,x.p) for x in CCm.bytknx(tkn0).bytkny(tkn1)]
        curve_prices += [(x.params['exchange'],x.descr,x.cid,1/x.p) for x in CCm.bytknx(tkn1).bytkny(tkn0)]
        return curve_prices
    
    # Global constant for Carbon Forks ordering
    CARBON_SORTING_ORDER = float('inf')

    # Create a sort order mapping function
    def create_sort_order(self, sort_sequence):
        # Create a dictionary mapping from sort sequence to indices, except for Carbon Forks
        return {key: index for index, key in enumerate(sort_sequence) if key not in self.ConfigObj.CARBON_V1_FORKS}

    # Define the sort key function separately
    def sort_key(self, item, sort_order):
        # Check if the item is Carbon Forks
        if item[0] in self.ConfigObj.CARBON_V1_FORKS:
            return self.CARBON_SORTING_ORDER
        # Otherwise, use the sort order from the dictionary, or a default high value
        return sort_order.get(item[0], self.CARBON_SORTING_ORDER - 1)

    # Define the custom sort function
    def custom_sort(self, data, sort_sequence):
        sort_order = self.create_sort_order(sort_sequence)
        return sorted(data, key=lambda item: self.sort_key(item, sort_order))

    def calculate_profit(
        self,
        CCm: CPCContainer,
        best_profit: Decimal,
        fl_token: str,
        flashloan_fee_amt: int = 0,
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Calculate the actual profit in USD.

        Parameters
        ----------
        CCm: CPCContainer
            The container.
        best_profit: Decimal
            The best profit.
        fl_token: str
            The flashloan token.
        flashloan_fee_amt: int
            The flashloan fee amount.

        Returns
        -------
        Tuple[Decimal, Decimal, Decimal]
            The updated best_profit, flt_per_bnt, and profit_usd.
        """
        self.ConfigObj.logger.debug(f"[bot.calculate_profit_usd] best_profit, fl_token, flashloan_fee_amt: {best_profit, fl_token, flashloan_fee_amt}")
        sort_sequence = ['bancor_v2','bancor_v3'] + self.ConfigObj.UNI_V2_FORKS + self.ConfigObj.UNI_V3_FORKS

        best_profit_fl_token = best_profit
        flashloan_fee_amt_fl_token = Decimal(str(flashloan_fee_amt))
        if fl_token not in [self.ConfigObj.WRAPPED_GAS_TOKEN_ADDRESS, self.ConfigObj.NATIVE_GAS_TOKEN_ADDRESS]:
            price_curves = self.get_prices_simple(CCm, self.ConfigObj.WRAPPED_GAS_TOKEN_ADDRESS, fl_token)
            sorted_price_curves = self.custom_sort(price_curves, sort_sequence)
            self.ConfigObj.logger.debug(f"[bot.calculate_profit sort_sequence] {sort_sequence}")
            self.ConfigObj.logger.debug(f"[bot.calculate_profit price_curves] {price_curves}")
            self.ConfigObj.logger.debug(f"[bot.calculate_profit sorted_price_curves] {sorted_price_curves}")
            if len(sorted_price_curves)>0:
                fltkn_gastkn_conversion_rate = sorted_price_curves[0][-1]
                flashloan_fee_amt_gastkn = Decimal(str(flashloan_fee_amt_fl_token)) / Decimal(str(fltkn_gastkn_conversion_rate))
                best_profit_gastkn = Decimal(str(best_profit_fl_token)) / Decimal(str(fltkn_gastkn_conversion_rate)) - flashloan_fee_amt_gastkn
                self.ConfigObj.logger.debug(f"[bot.calculate_profit] {fl_token, best_profit_fl_token, fltkn_gastkn_conversion_rate, best_profit_gastkn, 'GASTOKEN'}")
            else:
                self.ConfigObj.logger.error(
                    f"[bot.calculate_profit] Failed to get conversion rate for {fl_token} and {self.ConfigObj.WRAPPED_GAS_TOKEN_ADDRESS}. Raise"
                )
                raise
        else:
            best_profit_gastkn = best_profit_fl_token - flashloan_fee_amt_fl_token

        try:
            price_curves_usd = self.get_prices_simple(CCm, self.ConfigObj.WRAPPED_GAS_TOKEN_ADDRESS, self.ConfigObj.STABLECOIN_ADDRESS)
            sorted_price_curves_usd = self.custom_sort(price_curves_usd, sort_sequence)
            self.ConfigObj.logger.debug(f"[bot.calculate_profit price_curves_usd] {price_curves_usd}")
            self.ConfigObj.logger.debug(f"[bot.calculate_profit sorted_price_curves_usd] {sorted_price_curves_usd}")
            usd_gastkn_conversion_rate = Decimal(str(sorted_price_curves_usd[0][-1]))
        except Exception:
            usd_gastkn_conversion_rate = Decimal("NaN")

        best_profit_usd = best_profit_gastkn * usd_gastkn_conversion_rate
        self.ConfigObj.logger.debug(f"[bot.calculate_profit_usd] {'GASTOKEN', best_profit_gastkn, usd_gastkn_conversion_rate, best_profit_usd, 'USD'}")
        return best_profit_fl_token, best_profit_gastkn, best_profit_usd

    @staticmethod
    def update_log_dict(
        arb_mode: str,
        best_profit_gastkn: Decimal,
        best_profit_usd: Decimal,
        flashloan_tkn_profit: Decimal,
        calculated_trade_instructions: List[Any],
        fl_token: str,
    ) -> Dict[str, Any]:
        """
        Update the log dictionary.

        Parameters
        ----------
        arb_mode: str
            The arbitrage mode.
        best_profit: Decimal
            The best profit.
        best_profit_usd: Decimal
            The profit in USD.
        flashloan_tkn_profit: Decimal
            The profit from flashloan token.
        calculated_trade_instructions: List[Any]
            The calculated trade instructions.
        fl_token: str
            The flashloan token.

        Returns
        -------
        dict
            The updated log dictionary.
        """
        flashloans = [
            {
                "token": fl_token,
                "amount": num_format_float(calculated_trade_instructions[0].amtin),
                "profit": num_format_float(flashloan_tkn_profit),
            }
        ]
        log_dict = {
            "type": arb_mode,
            "profit_gas_token": num_format_float(best_profit_gastkn),
            "profit_usd": num_format_float(best_profit_usd),
            "flashloan": flashloans,
            "trades": [],
        }

        for idx, trade in enumerate(calculated_trade_instructions):
            tknin = {trade.tknin_symbol: trade.tknin} if trade.tknin_symbol != trade.tknin else trade.tknin
            tknout = {trade.tknout_symbol: trade.tknout} if trade.tknout_symbol != trade.tknout else trade.tknout
            log_dict["trades"].append(
                {
                    "trade_index": idx,
                    "exchange": trade.exchange_name,
                    "tkn_in": tknin,
                    "amount_in": num_format_float(trade.amtin),
                    "tkn_out": tknout,
                    "amt_out": num_format_float(trade.amtout),
                    "cid0": trade.cid[-10:],
                }
            )

        return log_dict

    def _handle_trade_instructions(
        self,
        CCm: CPCContainer,
        arb_mode: str,
        r: Any
    ) -> Any:
        """
        Handles the trade instructions.

        Parameters
        ----------
        CCm: CPCContainer
            The container.
        arb_mode: str
            The arbitrage mode.
        r: Any
            The result.

        Returns
        -------
        Any
            The result.
        """
        (
            best_profit,
            best_trade_instructions_df,
            best_trade_instructions_dic,
            best_src_token,
            best_trade_instructions,
        ) = r

        # Order the trade instructions
        (
            ordered_trade_instructions_dct,
            tx_in_count,
        ) = self._simple_ordering_by_src_token(
            best_trade_instructions_dic, best_src_token
        )

        # Scale the trade instructions
        ordered_scaled_dcts = self._basic_scaling(
            ordered_trade_instructions_dct, best_src_token
        )

        # Convert the trade instructions
        ordered_trade_instructions_objects = self._convert_trade_instructions(
            ordered_scaled_dcts
        )

        # Create the tx route handler
        tx_route_handler = self.TxRouteHandlerClass(
            trade_instructions=ordered_trade_instructions_objects
        )

        # Aggregate the carbon trades
        agg_trade_instructions = (
            tx_route_handler.aggregate_carbon_trades(ordered_trade_instructions_objects)
            if self._carbon_in_trade_route(ordered_trade_instructions_objects)
            else ordered_trade_instructions_objects
        )

        # Calculate the trade instructions
        calculated_trade_instructions = tx_route_handler.calculate_trade_outputs(
            agg_trade_instructions
        )

        # Aggregate multiple Bancor V3 trades into a single trade
        calculated_trade_instructions = tx_route_handler.aggregate_bancor_v3_trades(
            calculated_trade_instructions
        )

        flashloan_struct = tx_route_handler.generate_flashloan_struct(
            trade_instructions_objects=calculated_trade_instructions
        )

        # Get the flashloan token
        fl_token = calculated_trade_instructions[0].tknin_address
        fl_token_symbol = calculated_trade_instructions[0].tknin_symbol
        fl_token_decimals = calculated_trade_instructions[0].tknin_decimals
        flashloan_amount_wei = int(calculated_trade_instructions[0].amtin_wei)
        flashloan_fee = FLASHLOAN_FEE_MAP.get(self.ConfigObj.NETWORK, 0)
        flashloan_fee_amt = flashloan_fee * (flashloan_amount_wei / 10**int(fl_token_decimals))

        best_profit = flashloan_tkn_profit = tx_route_handler.calculate_trade_profit(
            calculated_trade_instructions
        )

        # Use helper function to calculate profit
        best_profit_fl_token, best_profit_gastkn, best_profit_usd = self.calculate_profit(
            CCm, best_profit, fl_token, flashloan_fee_amt
        )

        # Log the best trade instructions
        self.handle_logging_for_trade_instructions(
            1, best_profit=best_profit_gastkn  # The log id
        )

        # Use helper function to update the log dict
        log_dict = self.update_log_dict(
            arb_mode,
            best_profit_gastkn,
            best_profit_usd,
            flashloan_tkn_profit,
            calculated_trade_instructions,
            fl_token_symbol,
        )

        # Log the log dict
        self.handle_logging_for_trade_instructions(2, log_dict=log_dict)  # The log id

        # Check if the best profit is greater than the minimum profit
        if best_profit_gastkn < self.ConfigObj.DEFAULT_MIN_PROFIT_GAS_TOKEN:
            self.ConfigObj.logger.info(
                f"[bot._handle_trade_instructions] Opportunity with profit: {num_format(best_profit_gastkn)} does not meet minimum profit: {self.ConfigObj.DEFAULT_MIN_PROFIT_GAS_TOKEN}, discarding."
            )
            return None

        # Get the flashloan amount and token address
        flashloan_token_address = fl_token

        # Log the flashloan amount and token address
        self.handle_logging_for_trade_instructions(
            3,  # The log id
            flashloan_amount=flashloan_amount_wei,
        )

        # Split Carbon Orders
        split_calculated_trade_instructions = split_carbon_trades(
            cfg=self.ConfigObj,
            trade_instructions=calculated_trade_instructions
        )

        # Encode the trade instructions
        encoded_trade_instructions = tx_route_handler.custom_data_encoder(
            split_calculated_trade_instructions
        )

        # Get the deadline
        deadline = self._get_deadline(self.replay_from_block)

        # Get the route struct
        route_struct = [
            asdict(rs)
            for rs in tx_route_handler.get_route_structs(
                trade_instructions=encoded_trade_instructions, deadline=deadline
            )
        ]

        route_struct_processed = add_wrap_or_unwrap_trades_to_route(
            cfg=self.ConfigObj,
            flashloans=flashloan_struct,
            routes=route_struct,
            trade_instructions=split_calculated_trade_instructions,
        )

        route_struct_maximized = maximize_last_trade_per_tkn(route_struct=route_struct_processed)

        # Get the cids
        cids = list({ti["cid"] for ti in best_trade_instructions_dic})

        # Check if the network is tenderly and submit the transaction accordingly
        if self.ConfigObj.NETWORK == self.ConfigObj.NETWORK_TENDERLY:
            return submit_transaction_tenderly(
                cfg=self.ConfigObj,
                flashloan_struct=flashloan_struct,
                route_struct=route_struct_maximized,
                src_amount=flashloan_amount_wei,
                src_address=flashloan_token_address,
            )

        # Log the route_struct
        self.handle_logging_for_trade_instructions(
            4,  # The log id
            flashloan_amount=flashloan_amount_wei,
            flashloan_token_symbol=fl_token_symbol,
            flashloan_token_address=flashloan_token_address,
            route_struct=route_struct_maximized,
            best_trade_instructions_dic=best_trade_instructions_dic,
        )

        # Get the tx helpers class
        tx_helpers = TxHelpers(ConfigObj=self.ConfigObj)

        # Return the validate and submit transaction
        return tx_helpers.validate_and_submit_transaction(
            route_struct=route_struct_maximized,
            src_amt=flashloan_amount_wei,
            src_address=flashloan_token_address,
            expected_profit_gastkn=best_profit_gastkn,
            expected_profit_usd=best_profit_usd,
            safety_override=False,
            verbose=True,
            log_object=log_dict,
            flashloan_struct=flashloan_struct,
        )

    def handle_logging_for_trade_instructions(self, log_id: int, **kwargs):
        """
        Handles logging for trade instructions based on log_id.

        Parameters
        ----------
        log_id : int
            The ID for log type.
        **kwargs : dict
            Additional parameters required for logging.

        Returns
        -------
        None
        """
        log_actions = {
            1: self.log_best_profit,
            2: self.log_calculated_arb,
            3: self.log_flashloan_amount,
            4: self.log_flashloan_details,
        }
        log_action = log_actions.get(log_id)
        if log_action:
            log_action(**kwargs)

    def log_best_profit(self, best_profit: Optional[float] = None):
        """
        Logs the best profit.

        Parameters
        ----------
        best_profit : Optional[float], optional
            The best profit, by default None
        """
        self.ConfigObj.logger.debug(
            f"[bot.log_best_profit] Updated best_profit after calculating exact trade numbers: {num_format(best_profit)}"
        )

    def log_calculated_arb(self, log_dict: Optional[Dict] = None):
        """
        Logs the calculated arbitrage.

        Parameters
        ----------
        log_dict : Optional[Dict], optional
            The dictionary containing log data, by default None
        """
        self.ConfigObj.logger.info(
            f"[bot.log_calculated_arb] {log_format(log_data=log_dict, log_name='calculated_arb')}"
        )

    def log_flashloan_amount(self, flashloan_amount: Optional[float] = None):
        """
        Logs the flashloan amount.

        Parameters
        ----------
        flashloan_amount : Optional[float], optional
            The flashloan amount, by default None
        """
        self.ConfigObj.logger.debug(
            f"[bot.log_flashloan_amount] Flashloan amount: {flashloan_amount}"
        )

    def log_flashloan_details(
        self,
        flashloan_amount: Optional[float] = None,
        flashloan_token_address: Optional[str] = None,
        flashloan_token_symbol: Optional[str] = None,
        route_struct: Optional[List[Dict]] = None,
        best_trade_instructions_dic: Optional[Dict] = None,
    ):
        """
        Logs the details of flashloan.

        Parameters
        ----------
        flashloan_amount : Optional[float], optional
            The flashloan amount, by default None
        flashloan_token_symbol : Optional[str], optional
            The flashloan token symbol, by default None
        flashloan_token_address : Optional[str], optional
            The flashloan token address, by default None
        route_struct : Optional[List[Dict]], optional
            The route structure, by default None
        best_trade_instructions_dic : Optional[Dict], optional
            The dictionary containing the best trade instructions, by default None
        """
        self.ConfigObj.logger.debug(
            f"[bot.log_flashloan_details] Flashloan of {flashloan_token_symbol}, amount: {flashloan_amount}"
        )
        self.ConfigObj.logger.debug(
            f"[bot.log_flashloan_details] Flashloan token address: {flashloan_token_address}"
        )
        self.ConfigObj.logger.debug(
            f"[bot.log_flashloan_details] Route Struct: \n {route_struct}"
        )
        self.ConfigObj.logger.debug(
            f"[bot.log_flashloan_details] Trade Instructions: \n {best_trade_instructions_dic}"
        )

    def validate_mode(self, mode: str):
        """
        Validate the mode. If the mode is None, set it to RUN_CONTINUOUS.
        """
        if mode is None:
            mode = self.RUN_CONTINUOUS
        assert mode in [
            self.RUN_SINGLE,
            self.RUN_CONTINUOUS,
        ], f"Unknown mode {mode} [possible values: {self.RUN_SINGLE}, {self.RUN_CONTINUOUS}]"
        return mode

    def setup_polling_interval(self, polling_interval: int):
        """
        Setup the polling interval. If the polling interval is None, set it to RUN_POLLING_INTERVAL.
        """
        if self.polling_interval is None:
            self.polling_interval = (
                polling_interval
                if polling_interval is not None
                else self.RUN_POLLING_INTERVAL
            )

    def setup_flashloan_tokens(self, flashloan_tokens):
        """
        Setup the flashloan tokens. If flashloan_tokens is None, set it to RUN_FLASHLOAN_TOKENS.
        """
        return (
            flashloan_tokens
            if flashloan_tokens is not None
            else self.RUN_FLASHLOAN_TOKENS
        )

    def setup_CCm(self, CCm: CPCContainer) -> CPCContainer:
        """
        Setup the CCm. If CCm is None, retrieve and filter curves.

        Parameters
        ----------
        CCm: CPCContainer
            The CPCContainer object

        Returns
        -------
        CPCContainer
            The filtered CPCContainer object
        """
        if CCm is None:
            CCm = self.get_curves()
            if self.ConfigObj.ARB_CONTRACT_VERSION < 10:
                filter_out_weth = [
                    x
                    for x in CCm
                    if (x.params.exchange in self.ConfigObj.CARBON_V1_FORKS)
                    & (
                        (x.params.tkny_addr == self.ConfigObj.WETH_ADDRESS)
                        or (x.params.tknx_addr == self.ConfigObj.WETH_ADDRESS)
                    )
                ]
                CCm = CPCContainer([x for x in CCm if x not in filter_out_weth])
        return CCm

    def run_continuous_mode(
        self,
        flashloan_tokens: List[str],
        arb_mode: str,
        run_data_validator: bool,
        randomizer: int,
    ):
        """
        Run the bot in continuous mode.

        Parameters
        ----------
        flashloan_tokens: List[str]
            The flashloan tokens
        arb_mode: bool
            The arb mode
        """
        while True:
            try:
                CCm = self.get_curves()
                tx_hash = self._run(
                    flashloan_tokens,
                    CCm,
                    arb_mode=arb_mode,
                    data_validator=run_data_validator,
                    randomizer=randomizer,
                )
                if tx_hash:
                    self.ConfigObj.logger.info(f"Arbitrage executed [hash={tx_hash}]")

                time.sleep(self.polling_interval)
            except self.NoArbAvailable as e:
                self.ConfigObj.logger.debug(f"[bot:run:continuous] {e}")
            except Exception as e:
                self.ConfigObj.logger.error(f"[bot:run:continuous] {e}")
                time.sleep(self.polling_interval)

    def run_single_mode(
        self,
        flashloan_tokens: List[str],
        CCm: CPCContainer,
        arb_mode: str,
        run_data_validator: bool,
        randomizer: int,
        replay_mode: bool = False,
        tenderly_fork: str = None,
    ):
        """
        Run the bot in single mode.

        Parameters
        ----------
        flashloan_tokens: List[str]
            The flashloan tokens
        CCm: CPCContainer
            The complete market data container
        arb_mode: bool
            The arb mode
        replay_mode: bool
            Whether to run in replay mode
        tenderly_fork: str
            The Tenderly fork ID

        """
        try:
            if replay_mode:
                self._ensure_connection(tenderly_fork)

            tx_hash = self._run(
                flashloan_tokens=flashloan_tokens,
                CCm=CCm,
                arb_mode=arb_mode,
                data_validator=run_data_validator,
                randomizer=randomizer,
                replay_mode=replay_mode,
            )
            if tx_hash and tx_hash[0]:
                self.ConfigObj.logger.info(
                    f"[bot.run_single_mode] Arbitrage executed [hash={tx_hash}]"
                )

                # Write the tx hash to a file in the logging_path directory
                if self.logging_path:
                    filename = f"successful_tx_hash_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
                    print(f"Writing tx_hash hash {tx_hash} to {filename}")
                    with open(f"{self.logging_path}/{filename}", "w") as f:

                        # if isinstance(tx_hash[0], AttributeDict):
                        #     f.write(str(tx_hash[0]))
                        # else:
                        for record in tx_hash:
                            f.write("\n")
                            f.write("\n")
                            try:
                                json.dump(record, f, indent=4)
                            except:
                                f.write(str(record))

        except self.NoArbAvailable as e:
            self.ConfigObj.logger.warning(f"[NoArbAvailable] {e}")
        except Exception as e:
            self.ConfigObj.logger.error(f"[bot:run:single] {e}")
            raise

    def _ensure_connection(self, tenderly_fork: str):
        """
        Ensures connection to Tenderly fork.

        Parameters
        ----------
        tenderly_fork: str
            The Tenderly fork ID

        """

        tenderly_uri = f"https://rpc.tenderly.co/fork/{tenderly_fork}"
        self.db.cfg.w3 = Web3(Web3.HTTPProvider(tenderly_uri))
        self.ConfigObj.w3 = Web3(Web3.HTTPProvider(tenderly_uri))

    def get_tokens_in_exchange(
        self,
        exchange_name: str,
    ) -> List[str]:
        """
        Gets all tokens that exist in pools on the specified exchange.
        :param exchange_name: the exchange name
        """
        return self.db.get_tokens_from_exchange(exchange_name=exchange_name)

    def run(
        self,
        *,
        flashloan_tokens: List[str] = None,
        CCm: CPCContainer = None,
        polling_interval: int = None,
        mode: str = None,
        arb_mode: str = None,
        run_data_validator: bool = False,
        randomizer: int = 0,
        logging_path: str = None,
        replay_mode: bool = False,
        tenderly_fork: str = None,
        replay_from_block: int = None,
    ):
        """
        Runs the bot.

        Parameters
        ----------
        flashloan_tokens: List[str]
            The flashloan tokens (optional; default: self.RUN_FLASHLOAN_TOKENS)
        CCm: CPCContainer
            The complete market data container (optional; default: database via self.get_curves())
        polling_interval: int
            the polling interval in seconds (default: 60 via self.RUN_POLLING_INTERVAL)
        mode: RN_SINGLE or RUN_CONTINUOUS
            whether to run the bot one-off or continuously (default: RUN_CONTINUOUS)
        arb_mode: str
            the arbitrage mode (default: None)
        run_data_validator: bool
            whether to run the data validator (default: False)
        randomizer: int
            the randomizer (default: 0)
        logging_path: str
            the logging path (default: None)
        replay_mode: bool
            whether to run in replay mode (default: False)
        tenderly_fork: str
            the Tenderly fork ID (default: None)
        replay_from_block: int
            the block number to start replaying from (default: None)

        Returns
        -------
        str
            The transaction hash.
        """

        mode = self.validate_mode(mode)
        self.setup_polling_interval(polling_interval)
        flashloan_tokens = self.setup_flashloan_tokens(flashloan_tokens)
        CCm = self.setup_CCm(CCm)
        self.logging_path = logging_path
        self.replay_from_block = replay_from_block

        if arb_mode in {"bancor_v3", "b3_two_hop"}:
            run_data_validator = True
            # The following logs are used for asserting various pytests, do not remove.
            self.ConfigObj.logger.debug(
                f"[bot.run] Transactions will be required to pass data validation for {arb_mode}"
            )

        if mode == "continuous":
            self.run_continuous_mode(
                flashloan_tokens, arb_mode, run_data_validator, randomizer
            )
        else:
            self.run_single_mode(
                flashloan_tokens,
                CCm,
                arb_mode,
                run_data_validator,
                randomizer,
                replay_mode,
                tenderly_fork,
            )

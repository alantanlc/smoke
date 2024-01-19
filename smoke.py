import argparse
import yaml
import os
import logging
import requests
import json
import time
import datetime
import threading
import pdb
from time import perf_counter
import sys

class Smoke:

    def __init__(self):
        self.payloads = {}
        self.payloads_return = {}
        self.results = {}
        self.results_return = {}
        self.logger = logging.getLogger('gxp-smoke')
        self.headers = {'Accept': '*/*', 'Content-Type': 'application/json'}
        self.upload = "/".join([args.endpoint["base"], args.endpoint["upload"]]).replace('{env}', args.endpoint["env"])
        self.mock = "/".join([args.endpoint["base"], args.endpoint["mock"]])
        self.search = "/".join([args.endpoint["base"], args.endpoint["search"]]).replace('{env}', args.endpoint["env"])
        self.mocked = set()

    def load(self):
        """ Load json payloads """
        path_main = args.payload["upload"]["json"]["main"].replace('{env}', args.endpoint["env"])
        path_return = args.payload["upload"]["json"]["return"].replace('{env}', args.endpoint["env"])
        self.logger.info(f'Loading json payloads from directory: [{path_main}] ...')
        flows = [f for f in os.listdir(path_main) if f.endswith('json')]
        returns = [f for f in os.listdir(path_return) if f.endswith('json')]
        self.payloads = {}
        for flow in flows:
            # Load main payload
            with open("/".join([path_main, flow])) as payload:
                self.payloads[flow] = json.loads(payload.read())
            # Load return payload if exists
            if flow in returns:
                with open("/".join([path_return, flow])) as payload:
                    self.payloads_return[flow] = json.loads(payload.read())
        if args.payload["upload"]["valueDt"]:
            self.update_value_date()
        self.logger.info(f'Loaded {len(self.payloads)} payloads from {path_main}: {self.payloads.keys()}')
        self.logger.info(f'Loaded {len(self.payloads_return)} payloads from {path_return}: {self.payloads_return.keys()}')
        return self

    def update_value_date(self):
        """ Update value date. """
        for payload in self.payloads.keys():
            if '-' in payload:
                self.payloads[payload]["valueDt"] = str(args.payload["upload"]["valueDt"])
                if payload in self.payloads_return.keys():
                    self.payloads_return[payload]["valueDt"] = str(args.payload["upload"]["valueDt"])
            else:
                self.payloads[payload]["valueDt"] = str(args.payload["upload"]["valueDt"]).replace('-', '')
                if payload in self.payloads_return.keys():
                    self.payloads_return[payload]["valueDt"] = str(args.payload["upload"]["valueDt"]).replace('-', '')
        return self

    def smokes(self):
        """ Run smoke test for all flows in self.payloads """
        self.logger.info(f'Triggering smoke tests on {args.endpoint["env"].upper()} for all flows ...')
        self.results = {}
        self.results_return = {}
        threads = list()
        for flow in self.payloads.keys():
            t = threading.Thread(target=self.smoke_thread, args=(0, flow))
            threads.append(t)
            t.start()
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def smokes_return(self):
        """ Trigger return flows. """
        self.logger.info(f'Triggering smoke tests on {args.endpoint["env"].upper()} for return flows ...')
        threads = list()
        for flow, result in self.results.items():
            if flow in self.payloads_return.keys():
                # Get parent_firm_root_id and parent_p3_id
                parent_firm_root_id = result["response"].json()["firmRootId"]
                parent_p3_id = result["response"].json()["p3Id"]
                end_to_end_id = result["response"].json()["endToEndId"]
                # Update payload
                self.payloads_return[flow]["parentFirmRootId"] = parent_firm_root_id
                self.payloads_return[flow]["parentP3Id"] = parent_p3_id
                self.payloads_return[flow]["endToEndId"] = end_to_end_id
                t = threading.Thread(target=self.smoke_return_thread, args=(0, flow))
                threads.append(t)
                t.start()
        for index, thread in enumerate(threads):
            thread.join()
        return

    def update(self):
        """ Run smoke test for all incomplete flows in self.payloads """
        self.logger.info(f'Triggering smoke test on {args.endpoint["env"].upper()} for incomplete flows ...')
        threads = list()
        for flow in self.payloads.keys():
            if flow not in self.results.keys() or 'status' not in self.results[flow].keys() or self.results[flow]['status']['tranStatus'] not in ['CMP', 'RTN']:
                t = threading.Thread(target=self.smoke_thread, args=(0, flow))
                threads.append(t)
                t.start()
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def smoke(self, flow):
        """ Run smoke test for a given flow. """
        url = self.upload.replace('{service}', 'payment')
        if flow in self.payloads.keys():
            # Reset results
            self.results[flow] = {}

            # Update payloads
            if flow in self.mocked:
                self.payloads[flow]["businessLive"] = 'N'
                if flow in args.debit:
                    self.payloads[flow]["sanctionsResponse"] = 'PASSED'
                    self.payloads[flow]["fasResponse"] = 'Debit Req Ack'
                    self.payloads[flow]["postingResponse"] = 'Debit DDA Ack'
                else:
                    self.payloads[flow]["sanctionsResponse"] = 'PASSED'
                    self.payloads[flow]["fasResponse"] = 'Credit Req Ack'
                    self.payloads[flow]["postingResponse"] = 'Credit DDA Ack'
            else:
                self.payloads[flow]["businessLive"] = 'Y'
                self.payloads[flow]["sanctionsResponse"] = ''
                self.payloads[flow]["fasResponse"] = ''
                self.payloads[flow]["postingResponse"] = ''

            # Request
            self.results[flow]["response"] = requests.post(url, data=json.dumps(self.payloads[flow]), headers=self.headers)

            # Response
            if self.results[flow]["response"].status_code == 200:
                self.logger.info(f'Request for [{flow}] was successful, id = {self.get_id(flow)["id"]}')
            else:
                self.logger.warning(f'Request for [{flow}] was unsuccessful')
        else:
            self.logger.error(f'[{flow}] not found.')
        return self

    def get_id(self, flow):
        """ Returns firmRootId or endToEndId for a given flow result. """
        result = {"id": "Not found", "type": "NA"}
        if flow in self.results.keys():
            if self.results[flow]["response"].json()["firmRootId"]:
                result["id"] = self.results[flow]["response"].json()["firmRootId"]
                result["type"] = "FIRM_ROOT_ID"
            elif self.results[flow]["response"].json()["endToEndId"]:
                result["id"] = self.results[flow]["response"].json()["endToEndId"]
                result["type"] = "END_TO_END_ID"
        return result

    def get_return_id(self, flow):
        """ Returns firmRootId or endToEndId for a given return flow result. """
        result = {"id": "Not found", "type": "NA"}
        if flow in self.results_return.keys():
            if self.results_return[flow]["response"].json()["firmRootId"]:
                result["id"] = self.results_return[flow]["response"].json()["firmRootId"]
                result["type"] = "FIRM_ROOT_ID"
            elif self.results_return[flow]["response"].json()["endToEndId"]:
                result["id"] = self.results_return[flow]["response"].json()["endToEndId"]
                result["type"] = "END_TO_END_ID"
        return result

    def get_transaction_status(self, firm_root_id):
        """ Get transaction status by firmRootId. """
        url = self.search.replace('{region}', 'TransactionStatus').replace('{ids}', firm_root_id)
        response = requests.get(url)
        if response.status_code == 200 and len(response.json()) != 0:
            return response.json()[0]
        return ""

    def get_name(self, flow):
        """ Return formatted name of flow. 'flow' is the name of the payload json file. """
        return " ".join(flow[:-5].split('_')).upper()

    def get_firm_root_id(self, flow, results):
        """ Get firm_root_id from self.results by flow. """
        if results[flow]["response"].json()["firmRootId"]:
            return results[flow]["response"].json()["firmRootId"]
        elif 'firm_root_id' in results[flow] and results[flow]["firm_root_id"]:
            return results[flow]["firm_root_id"]
        else:
            url = self.search.replace('{region}', 'TransactionDetail').replace('{ids}', self.results[flow]["response"].json()["endToEndId"]).replace('FIRM_ROOT_ID', 'END_TO_END_ID')
            response = requests.get(url)
            if response.status_code == 200 and len(response.json()) != 0:
                results[flow]["firm_root_id"] = response.json()[0]["firmRootId"]
                return results[flow]["firm_root_id"]
        return ""

    def get_p3_id(self, flow, results):
        """ Get p3_id from results by flow. """
        if results[flow]["response"].json()["p3Id"]:
            return results[flow]["response"].json()["p3Id"]
        elif 'p3_id' in results[flow] and results[flow]["p3_id"]:
            return results[flow]["p3_id"]
        else:
            url = self.search.replace('{region}', 'TransactionDetail').replace('{ids}', results[flow]["firm_root_id"])
            response = requests.get(url)
            if response.status_code == 200 and len(response.json()) != 0:
                results[flow]["p3_id"] = response.json()[0]["p3Id"]
                return results[flow]["p3_id"]
        return ""

    def report_2(self, verbose, update_returns=False):
        """ Print report of smoke test in self.results """
        self.logger.info(f'Updating statuses and p3_id ...')

        # Update main results
        threads = list()
        for flow in self.results.keys():
            t = threading.Thread(target=self.update_result, args=(0, flow, self.results))
            threads.append(t)
            t.start()

        # Update return results
        for flow in self.results_return.keys():
            t = threading.Thread(target=self.update_result, args=(0, flow, self.results_return))
            threads.append(t)
            t.start()

        # Join threads
        for index, thread in enumerate(threads):
            thread.join()

        # Print results
        self.logger.info(f'Printing test report ...')
        print(f'\n[Smoke test on {time.ctime().upper()} - {args.endpoint["env"]}]\n'.upper())
        for flow, result in sorted(self.results.items()):
            if update_returns and flow in self.results_return.keys():
                name = self.get_name(flow)
                firm_root_id = self.get_firm_root_id(flow, self.results_return)
                p3_id = self.get_p3_id(flow, self.results_return)
                status = self.results_return[flow]["status"]
            else:
                name = self.get_name(flow)
                firm_root_id = self.get_firm_root_id(flow, self.results)
                p3_id = self.get_p3_id(flow, self.results)
                status = result["status"]
            if verbose:
                print(f'{name}: {firm_root_id} / {p3_id} - {self.get_service_statuses(status)}{self.get_business_live_n_text(flow)}')
            elif status != '':
                print(f'{name}: {firm_root_id} / {p3_id} - {status["tranStatus"]}{self.get_business_live_n_text(flow)}')
            else:
                print(f'{name}: {firm_root_id} / {p3_id} - {status}{self.get_business_live_n_text(flow)}')

        print(f'\n[END]\n')

        return self

    def save(self):
        """ Save smoke test result to log file """
        file_name = f'gxp-smoke-test-{datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}.log'
        with open(f'smoke/{args.endpoint["env"]}/{file_name}', 'w') as f:
            f.write(f'[Smoke test on {time.ctime().upper()} - {args.endpoint["env"]}]\n'.upper())
            for flow, result in sorted(self.results.items()):
                name = self.get_name(flow)
                firm_root_id = self.get_firm_root_id(flow, self.results)
                p3_id = self.get_p3_id(flow, self.results)
                status = result["status"]
                f.write(f'\n{name}: {firm_root_id} / {p3_id} - {self.get_service_statuses(status)}{self.get_business_live_n_text(flow)}')
            f.write(f'\n\n[END]\n')
            self.logger.info(f'Smoke test result saved to [smoke/{args.endpoint["env"]}/{file_name}]')
        return self

    def update_result(self, name, flow, results):
        """ Get transaction status and p3Id of flow. """
        if flow in results.keys():
            # Update firm_root_id
            if 'firm_root_id' not in results[flow].keys():
                results[flow]["firm_root_id"] = self.get_firm_root_id(flow, results)

            # Update status
            results[flow]["status"] = self.get_transaction_status(results[flow]["firm_root_id"])

            # Update p3_id
            if 'p3_id' not in results[flow].keys():
                results[flow]["p3_id"] = self.get_p3_id(flow, results)

        return self

    def get_business_live_n_text(self, flow):
        """ Return business live n text if transaction was triggered with isBusinessLive as 'N'. """
        if flow in self.mocked:
            return f'\t(Triggered with isBusinessLive \'N\' and mocking)'
        return ""

    def get_service_statuses(self, transactionStatus):
        """ Return service statuses. """
        if not transactionStatus:
            return ""
        qual = transactionStatus['qualificationStatus']
        sanctions = transactionStatus['sanctionsStatus']
        funds = transactionStatus['fundsControlStatus']
        post = transactionStatus['postStatus']
        sett = transactionStatus['settStatus']
        tran = transactionStatus['tranStatus']
        return f'Qual = {qual}, Sanctions = {sanctions}, Funds = {funds}, Posting = {post}, Sett = {sett}, Tran = {tran}'

    def get_clearing_system(self, flow):
        """ Return clearing system. """
        if 'sgp' in flow:
            return 'SG_FAST'
        elif 'mys' in flow:
            return 'MY_RPP'
        else:
            return 'AU_NPP'

    def mock_thread(self, service, response_value, flow, results):
        """ Mock a service response for a transaction. """
        url = self.mock.replace('{service}', service)
        if flow in results.keys():
            firm_root_id = self.get_firm_root_id(flow, results)
            response_key = f'{args.payload["mock"][service]["key"]}'
            payload = {"firmRootId": firm_root_id, response_key: response_value, "clearingSystem": self.get_clearing_system(flow)}
            response = requests.post(url, data=json.dumps([payload]), headers=self.headers)
            if response.status_code == 200:
                self.logger.info(f'Mocking {service} with {response_value.upper()} for [{flow}] was successful, firmRootId = {firm_root_id}')
            else:
                self.logger.warning(f'Mocking {service} with {response_value.upper()} for [{flow}] failed, firmRootId = {firm_root_id}')
        else:
            self.logger.error(f'[{flow}] not found')
        return self

    def mock_sanctions(self):
        """ Mock sanctions for all transactions. """
        self.logger.info(f'Mocking sanctions for all transactions ...')
        response_value = ''
        threads = list()
        # Main
        for flow in self.results.keys():
            response_value = "FAILED_REJECT" if args.sanctions_reject and flow in args.sanctions_reject else "PASSED"
            t = threading.Thread(target=self.mock_thread, args=('sanctions', response_value, flow, self.results))
            threads.append(t)
            t.start()
        # Return
        for flow in self.results_return.keys():
            response_value = "FAILED_REJECT" if args.sanctions_reject and flow in args.sanctions_reject else "PASSED"
            t = threading.Thread(target=self.mock_thread, args=('sanctions', response_value, flow, self.results_return))
            threads.append(t)
            t.start()
        # Join
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def mock_funds(self):
        """ Mock funds for all transactions. """
        self.logger.info(f'Mocking funds for all transactions ...')
        response_value = ''
        threads = list()
        # Main
        for flow in self.results.keys():
            response_value = "dr:rq:yes" if args.debit and flow in args.debit else "cr:rq:yes"
            t = threading.Thread(target=self.mock_thread, args=('fundcontrol', response_value, flow, self.results))
            threads.append(t)
            t.start()
        # Return
        for flow in self.results_return.keys():
            response_value = "cr:rq:yes" if args.debit and flow in args.debit else "dr:rq:yes"
            t = threading.Thread(target=self.mock_thread, args=('fundcontrol', response_value, flow, self.results_return))
            threads.append(t)
            t.start()
        # Join
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def mock_posting(self):
        """ Mock posting for all transactions. """
        self.logger.info(f'Mocking posting for all transactions ...')
        response_value = ''
        threads = list()
        # Main
        for flow in self.results.keys():
            response_value = "dr:dda:ack" if args.debit and flow in args.debit else "cr:dda:ack"
            t = threading.Thread(target=self.mock_thread, args=('posting', response_value, flow, self.results))
            threads.append(t)
            t.start()
        # Return
        for flow in self.results_return.keys():
            response_value = "cr:dda:ack" if args.debit and flow in args.debit else "dr:dda:ack"
            t = threading.Thread(target=self.mock_thread, args=('posting', response_value, flow, self.results_return))
            threads.append(t)
            t.start()
        # Join
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def mock_funds_book(self):
        """ Mock funds as 'Credit Req Ack' for all book transactions. """
        self.logger.info(f'Mocking funds for all book transactions ...')
        response_value = ''
        threads = list()
        for flow in self.results.keys():
            if 'book' in flow:
                response_value = "cr:rq:ack"
                t = threading.Thread(target=self.mock_thread, args=('fundcontrol', response_value, flow, self.results))
                threads.append(t)
                t.start()
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def mock_posting_book(self):
        """ Mock posting as 'Credit DDA Ack' for all book transactions. """
        self.logger.info(f'Mocking posting for all book transactions ...')
        response_value = ''
        threads = list()
        for flow in self.results.keys():
            if 'book' in flow:
                response_value = "cr:dda:ack"
                t = threading.Thread(target=self.mock_thread, args=('posting', response_value, flow, self.results))
                threads.append(t)
                t.start()
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def mock_clearing(self):
        """ Mock clearing for all transactions. """
        self.logger.info(f'Mocking clearing for all transactions ...')
        response_value = ''
        threads = list()
        # Main
        for flow in self.results.keys():
            response_value = "Technical Ack, Settlement Ack"
            t = threading.Thread(target=self.mock_thread, args=('clearing', response_value, flow, self.results))
            threads.append(t)
            t.start()
        # Return
        for flow in self.results_return.keys():
            response_value = "Technical Ack, Settlement Ack"
            t = threading.Thread(target=self.mock_thread, args=('clearing', response_value, flow, self.results_return))
            threads.append(t)
            t.start()
        # Join
        for index, thread in enumerate(threads):
            thread.join()
        return self

    def extraction(self, tps, mins):
        """ Trigger extraction bulk for a given TPS and duration in mins. """
        seconds = mins * 60
        num_transactions = tps * mins * 60
        self.logger.info(f'Triggering {num_transactions} extraction bulk with {tps} transactions per second for {mins} ...')

        # Wait until 200 ms before the 0th second
        current_milliseconds = int(time.time() * 1000) % 1000
        while current_milliseconds < 800:
            current_milliseconds = int(time.time() * 1000) % 1000

        # Start triggering
        start = perf_counter()
        for j in range(seconds):

            # Wait until the 0th second
            current_milliseconds = int(time.time() * 1000) % 1000
            while current_milliseconds > 50:
                current_milliseconds = int(time.time() * 1000) % 1000

            # Spawn threads
            self.logger.info(f'Triggering {tps} transactions at {time.ctime()}')
            for i in range(tps):
                t = threading.Thread(target=self.extraction_thread, args=(j*tps+i+1,'extraction_bulk'))
                t.start()

                # Sleep awhile to space out requests
                time.sleep(0.05)

            # Sleep for 50 milliseconds
            time.sleep(0.05)

        t.join()
        end = perf_counter()
        execution_time = (end - start)

        # Compute performance
        execution_minutes = execution_time // 60
        execution_seconds = execution_time % 60
        mean_tps = num_transactions / execution_time

        # Sleep for awhile
        time.sleep(3)

        self.logger.info(f'Triggered {num_transactions} extraction bulk in [{execution_minutes} mins {execution_seconds} seconds] ({execution_time} seconds)')
        self.logger.info(f'Mean TPS (transactions per second): {mean_tps}')
        return self

    def extraction_thread(self, name, flow):
        """ Extraction thread """
        url = args.endpoint["extraction"]

        # Post request
        response = requests.post(url, headers=self.headers)

        # Response
        if response.status_code == 200:
            self.logger.info(f'Request for [{flow}] was successful. firmRootIds = {[f for f in response.json()]}')
        else:
            self.logger.warning(f'Request for [{flow}] was unsuccessful')

        return self

    def industry(self, flow, tps, mins):
        """ Trigger flow for a given TPS and duration in mins. """
        seconds = mins * 60
        num_transactions = tps * mins * 60
        additionalRemittanceInfo = self.payloads[flow]["additionalRemittanceInfo"]
        self.logger.info(f'Triggering {num_transactions} [{flow}] with {tps} transactions per second for {mins} minutes using additionalRemittanceInfo as [{additionalRemittanceInfo}]...')

        # Wait until 200 ms before the 0th second
        current_milliseconds = int(time.time() * 1000) % 1000
        while current_milliseconds < 800:
            current_milliseconds = int(time.time() * 1000) % 1000

        # Start triggering
        start = perf_counter()
        for j in range(seconds):

            # Wait until the 0th second
            current_milliseconds = int(time.time() * 1000) % 1000
            while current_milliseconds > 50:
                current_milliseconds = int(time.time() * 1000) % 1000

            # Spawn threads
            self.logger.info(f'Triggering {tps} transactions at {time.ctime()}')
            for i in range(tps):
                t = threading.Thread(target=self.smoke_thread, args=(j*tps+i+1, flow))
                t.start()

                # Sleep awhile to space out requests
                time.sleep(0.02)

            # Sleep for 50 milliseconds
            time.sleep(0.05)

        t.join()
        end = perf_counter()
        execution_time = (end - start)

        # Compute performance
        execution_minutes = execution_time // 60
        execution_seconds = execution_time % 60
        mean_tps = num_transactions / execution_time

        # Sleep for awhile
        time.sleep(3)

        self.logger.info(f'Triggered {num_transactions} [{flow}] in [{execution_minutes} mins {execution_seconds} seconds] ({execution_time} seconds)')
        self.logger.info(f'Mean TPS (transactions per second): {mean_tps}')
        return self

    def smoke_thread(self, name, flow):
        """ Smoke thread """
        url = self.upload.replace('{service}', 'payment')
        self.results[flow] = {}

        # Update payloads
        # if flow in self.mocked:
        #     self.payloads[flow]["businessLive"] = 'N'
        #     if flow in args.debit:
        #         self.payloads[flow]["sanctionsResponse"] = 'PASSED'
        #         self.payloads[flow]["fasResponse"] = 'Debit Req Ack'
        #         self.payloads[flow]["postingResponse"] = 'Debit DDA Ack'
        #     else:
        #         self.payloads[flow]["sanctionsResponse"] = 'PASSED'
        #         self.payloads[flow]["fasResponse"] = 'Credit Req Ack'
        #         self.payloads[flow]["postingResponse"] = 'Credit DDA Ack'
        # else:
        #     self.payloads[flow]["businessLive"] = 'Y'
        #     self.payloads[flow]["sanctionsResponse"] = ''
        #     self.payloads[flow]["fasResponse"] = ''
        #     self.payloads[flow]["postingResponse"] = ''

        # Request
        self.results[flow]["response"] = requests.post(url, data=json.dumps(self.payloads[flow]), headers=self.headers)

        # Response
        if self.results[flow]["response"].status_code == 200:
            self.logger.info(f'Request for [{flow}] was successful, id = {self.get_id(flow)["id"]}')
        else:
            self.logger.warning(f'Request for [{flow}] was unsuccessful')
        return self

    def smoke_return_thread(self, name, flow):
        """ Smoke return thread """
        url = self.upload.replace('{service}', 'payment')
        self.results_return[flow] = {}

        # Update payloads
        if flow in self.mocked:
            self.payloads_return[flow]["businessLive"] = 'N'
            if flow not in args.debit:
                self.payloads_return[flow]["sanctionsResponse"] = 'PASSED'
                self.payloads_return[flow]["fasResponse"] = 'Debit Req Ack'
                self.payloads_return[flow]["postingResponse"] = 'Debit DDA Ack'
            else:
                self.payloads_return[flow]["sanctionsResponse"] = 'PASSED'
                self.payloads_return[flow]["fasResponse"] = 'Credit Req Ack'
                self.payloads_return[flow]["postingResponse"] = 'Credit DDA Ack'
        else:
            self.payloads_return[flow]["businessLive"] = 'Y'
            self.payloads_return[flow]["sanctionsResponse"] = ''
            self.payloads_return[flow]["fasResponse"] = ''
            self.payloads_return[flow]["postingResponse"] = ''

        # Request
        self.results_return[flow]["response"] = requests.post(url, data=json.dumps(self.payloads_return[flow]), headers=self.headers)

        # Response
        if self.results_return[flow]["response"].status_code == 200:
            self.logger.info(f'Request for [{flow}] was successful, id = {self.get_return_id(flow)["id"]}, parent_firm_root_id = {self.payloads_return[flow]["parentFirmRootId"]}, parent_p3_id = {self.payloads_return[flow]["parentP3Id"]}, end_to_end_id = {self.payloads_return[flow]["endToEndId"]}')
        else:
            self.logger.warning(f'Request for [{flow}] was unsuccessful')
        return self

    def toggle_source_system(self):
        """ Toggle source system for incoming transactions. """
        for flow in self.payloads.keys():
            if 'rrct' in flow or 'rddt' in flow:
                if self.payloads[flow]["sourceSystem"].lower() == 'gc2':
                    self.payloads[flow]["sourceSystem"] = 'gxp'
                    self.logger.info(f'Source system for {[flow]} is now set to [gxp]')
                else:
                    self.payloads[flow]["sourceSystem"] = 'gc2'
                    self.logger.info(f'Source system for {[flow]} is now set to [gc2]')
        return self

    def reset_additional_remittance_info(self):
        """ Reset unstructRemitInfo for all payloads """
        for flow in s.payloads.keys():
            s.payloads[flow]["additionalRemittanceInfo"] = 'Additional Remittance Info'
        return self

    def soak(self, tpi, mpi, mins, unstrucRemitInfo1):
        """ Soak test."""
        seconds = mins * 60
        num_transactions = tpi * (mins / mpi)
        self.logger.info(f'Triggering {num_transactions} [sgp_irct_dmct.json, sgp_iddt_pmdd.json] with {tpi} transactions each every {mpi} mins for {mins} mins using unstructRemitInfo1 as [{unstrucRemitInfo1}] ...')

        # Set unstrucRemitInfo
        self.payloads["sgp_irct_dmct.json"]["additionalRemittanceInfo"] = unstrucRemitInfo1
        self.payloads["sgp_iddt_pmdd.json"]["additionalRemittanceInfo"] = unstrucRemitInfo1

        # Start triggering
        start = perf_counter()
        while True:

            # Trigger transactions
            self.logger.info(f'Triggering {tpi * 2} transactions at {time.ctime()}')
            t = threading.Thread(target=self.smoke_thread, args=(0, 'sgp_irct_dmct.json'))
            t.start()
            t = threading.Thread(target=self.smoke_thread, args=(0, 'sgp_irct_dmct.json'))
            t.start()
            t = threading.Thread(target=self.smoke_thread, args=(0, 'sgp_iddt_pmdd.json'))
            t.start()
            t = threading.Thread(target=self.smoke_thread, args=(0, 'sgp_iddt_pmdd.json'))
            t.start()

            # Sleep for interval
            self.logger.info(f'Sleeping for {mpi} mins ...')
            time.sleep(60 * mpi)

        t.join()
        end = perf_counter()
        execution_time = (end - start)

        # Computer performance
        execution_minutes = execution_time // 60
        execution_seconds = execution_time % 60
        mean_tpe = num_transactions / execution_time

        # Sleep for awhile
        time.sleep(3)

        return self

if __name__ == '__main__':
    # argparse
    parser = argparse.ArgumentParser(description='Use GXP Smoke to run smoke tests and generate report.')
    parser.add_argument('-y', '--yaml', type=str, help='(Deprecated) name of yaml config file')
    parser.add_argument('-e', '--env', type=str, default='ua1', help='environment to trigger smoke tests on. Possible values are: dev, qa1, qa2, ua1, ua2, ua3, ua4, perf')
    args = parser.parse_args()

    # Load config based on -y or --yaml flag
    if args.yaml:
        print(f'NOTE: The -y and --yaml flags have been deprecated. Please use -e or --env to specify the environment during startup instead. For more info, run python smoke.py --help')
        sys.exit()

    # Load config based on -e or --env flag
    if args.env:
        path = f'config/{args.env}/config.yaml'
        if not os.path.exists(path):
            print(f'{path} not found!')
            sys.exit()
        with open(path) as f:
            data = yaml.load(f, Loader=yaml.FullLoader)
            for k, v in data.items():
                args.__setattr__(k, v)

    # logging
    if not os.path.exists('log'):
        os.makedirs('log')
    if not os.path.exists(f'log/{args.endpoint["env"]}'):
        os.makedirs(f'log/{args.endpoint["env"]}')
    logging.basicConfig(level=logging.INFO,
            format='%(asctime)s %(threadName)-12s %(name)-12s %(levelname)-8s %(message)s',
            handlers=[
                logging.FileHandler(f'./log/{args.endpoint["env"]}/gxp-smoke-{time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())}.log'),
                logging.StreamHandler()
            ])

    # smoke logging
    if not os.path.exists('smoke'):
        os.makedirs('smoke')
    if not os.path.exists(f'smoke/{args.endpoint["env"]}'):
        os.makedirs(f'smoke/{args.endpoint["env"]}')

    # smoke
    s = Smoke()
    s.load()

    # report
    x = ''
    while x != 'q' and x != 'quit':
        try:
            if x == 'all' or x == 'a':
                s.smokes()
            elif x == 'update' or x == 'u':
                s.update()
            elif x == 'result' or x == 'r':
                s.report_2(verbose=False)
            elif x == 'resultreturn' or x == 'rr':
                s.report_2(verbose=False, update_returns=True)
            elif x == 'verbose' or x == 'v':
                s.report_2(verbose=True)
            elif x == 'verbosereturn' or x == 'vr':
                s.report_2(verbose=True, update_returns=True)
            elif x == 'payload' or x == 'p':
                print(f'Which payload would you like to check?')
                print(f'{s.payloads.keys()}')
                print(f'Enter \'all\' to print all payloads.')
                payload = input()
                if payload == 'all':
                    for payload in s.payloads.keys():
                        print(payload)
                        print(json.dumps(s.payloads[payload], indent=4, sort_keys=False))
                        print('')
                elif payload in s.payloads.keys():
                    print(json.dumps(s.payloads[payload], indent=4, sort_keys=False))
                else:
                    print(f'Payload for {payload} is not found')
            elif x == 'status' or x == 'st':
                flows = set('flows')
                while flows.difference(set(s.results.keys())):
                    print(f'Which flows would you like to check? Separate flows by space.')
                    print(f'{s.results.keys()}')
                    flows = set(str(input().replace("'", '')).split(' '))
                for flow in flows:
                    name = s.get_name(flow)
                    firm_root_id = s.results[flow].json()["firmRootId"]
                    p3_id = s.get_p3_id(flow, s.results)
                    status = s.get_transaction_status(firm_root_id)
                    if status != '':
                        print(f'{name} \t{firm_root_id} / {p3_id} \t{s.get_service_statuses(status)}{s.get_business_live_n_text(flow)}')
                    else:
                        print(f'{name} \t{firm_root_id} / {p3_id} \t{status}{s.get_business_live_n_text(flow)}')
            elif x == 'mock' or x == 'mo':
                flows = set('flows')
                while flows.difference(set(s.results.keys())):
                    print(f'Which flows would you like to mock? Separate flows by space.')
                    print(f'{s.results.keys()}')
                    flows = set(str(input().replace("'", '')).split(' '))
                service = 'service'
                while service not in args.payload["mock"].keys():
                    print(f'Which service would you like to mock?')
                    print(f'{args.payload["mock"].keys()}')
                    service = input().replace("'", '')
                response_value = 'response_value'
                while response_value not in args.payload["mock"][service]["values"]:
                    print(f'Which response would you like to mock?')
                    print(f'{args.payload["mock"][service]["values"]}')
                    response_value = input().replace("'", '')
                for flow in flows:
                    s.mock(service, response_value, flow)
            elif x == 'load' or x == 'l':
                s.load()
            elif x == 'one' or x == 'o':
                flows = set('flows')
                while flows.difference(set(s.payloads.keys())):
                    print(f'Which flows would you like to re-run smoke test? Separate flows by space.')
                    print(f'{s.payloads.keys()}')
                    flows = set(str(input().replace("'", '')).split(' '))
                for flow in flows:
                    s.smoke(flow)
            elif x == 'businesslivet' or x == 'bt':
                flows = set('flows')
                while flows.difference(set(s.payloads.keys())):
                    print(f'Which flows would you like to toggle isBusinessLive flag?')
                    print(f'Mocked (current): {s.mocked}')
                    print(f'Not mocked (current): {set(s.payloads.keys()).difference(s.mocked)}')
                    print(f'Separate flows by space. Enter \'all\' to toggle all:')
                    flows = input().replace("'", '')
                    if flows == 'all':
                        flows = set(s.payloads.keys())
                    else:
                        flows = set(str(flows).split(' '))
                for flow in flows:
                    if flow in s.mocked:
                        s.mocked.remove(flow)
                    else:
                        s.mocked.add(flow)
                print(f'Mocked (new): {s.mocked}')
                print(f'Not mocked (new): {set(s.payloads.keys()).difference(s.mocked)}')
            elif x == 'businesslivey' or x == 'by':
                s.mocked = set()
                print(f'Mocked (new): {s.mocked}')
                print(f'Not mocked (new): {set(s.payloads.keys()).difference(s.mocked)}')
            elif x == 'businessliven' or x == 'bn':
                s.mocked = set(s.payloads.keys())
                print(f'Mocked (new): {s.mocked}')
                print(f'Not mocked (new): {set(s.payloads.keys()).difference(s.mocked)}')
            elif x == 'mocksanctions' or x == 'ms':
                s.mock_sanctions()
            elif x == 'mockfunds' or x == 'mf':
                s.mock_funds()
            elif x == 'mockposting' or x == 'mp':
                s.mock_posting()
            elif x == 'mockfundsbook' or x == 'mfb':
                s.mock_funds_book()
            elif x == 'mockpostingbook' or x == 'mpb':
                s.mock_posting_book()
            elif x == 'mockclearing' or x == 'mc':
                s.mock_clearing()
            elif x == 'yaml' or x == 'y':
                with open(args.yaml) as f:
                    data = yaml.load(f, Loader=yaml.FullLoader)
                    for k, v in data.items():
                        args.__setattr__(k, v)
            elif x == 'tps' or x == 'nt':
                flow = ''
                while flow not in s.payloads.keys():
                    print(f'Which flow would you like to trigger continuously?')
                    print(f'{s.payloads.keys()}')
                    flow = input()
                print(f'How many transactions per second?')
                tps = int(input())
                print(f'For how many minutes?')
                mins = int(input())

                # Update unstrucRemitInfo for post analysis
                default_name = f'NFT_{tps}TPS_{mins}MIN_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
                print(f'What unstrucRemitInfo to use? (Enter for \'{default_name}\')')
                name = input()
                if name == '':
                    name = default_name
                s.payloads[flow]["additionalRemittanceInfo"] = name
                s.industry(flow, tps, mins)
            elif x == 'extraction' or x == 'ne':
                print(f'How many transactions per second?')
                tps = int(input())
                print(f'For how many minutes?')
                mins = int(input())
                s.extraction(tps, mins)
            elif x == 'togglesource' or x == 'ts':
                s.toggle_source_system()
            elif x == 'soak' or x == 'ns':
                print(f'How many transactions per interval?')
                tpi = int(input())
                print(f'How many minutes is each interval?')
                interval = int(input())
                print(f'For how many minutes?')
                mins = int(input())

                # Update unstrucRemitInfo for post analysis
                default_name = f'NFT_{tpi}TPI_{interval}MI_{mins}MIN_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
                print(f'What unstrucRemitInfo to use? (Enter for \'{default_name}\')')
                name = input()
                if name == '':
                    name = default_name
                s.soak(tpi, interval, mins, name)
            elif x == 'save' or x == 'sv':
                s.save()
            elif x == 'return' or x == 're':
                s.smokes_return()
        except:
            pass

        # Reset additional remittance info
        s.reset_additional_remittance_info()

        # User prompt
        print(f"\nWhat would you like to do next?")

        # Smoke
        print(f"Smoke")
        print(f"  'a' or 'all' \t\t\t smoke test for all transactions")
        print(f"  'o' or 'one' \t\t\t smoke test for input transactions")
        print(f"  'u' or 'update' \t\t smoke test for incomplete transactions")
        print(f"  're' or 'return' \t\t smoket test for return/reversal/cancellation transactions")

        # Result
        print(f"Result")
        print(f"  'r' or 'result' \t\t print results with tranStatus")
        print(f"  'rr' or 'resultreturn' \t print results with tranStatus and returns updated")
        print(f"  'v' or 'verbose' \t\t print results with all statuses")
        print(f"  'vr' or 'verbosereturn' \t print results with all statuses and returns updated")
        print(f"  'st' or 'status' \t\t print result of one transaction with all statuses")
        print(f"  'sv' or 'save' \t\t save results with all statuses")

        # Source System
        print(f"Source System")
        print(f"  'ts' or 'togglesource' \t toggle source system for incoming transactions")

        # Business Live
        print(f"Business Live")
        print(f"  'bt' or 'businesslivet' \t toggle isBusinessLive for one or all flows")
        print(f"  'by' or 'businesslivey' \t set isBusinessLive to Y for all flows")
        print(f"  'bn' or 'businessliven' \t set isBusinessLive to N for all flows")

        # Mocking
        print(f"Mocking")
        print(f"  'mo' or 'mock' \t\t mock response for given transactions")
        print(f"  'ms' or 'mocksanctions' \t mock sanctions for all transactions")
        print(f"  'mf' or 'mockfunds' \t\t mock funds for all transactions")
        print(f"  'mc' or 'mockclearing' \t mock clearing for all transactions")
        print(f"  'mp' or 'mockposting' \t mock posting for all transactions")
        print(f"  'mfb' or 'mockfundsbook' \t mock funds 'Credit Req Ack' for all book transactions")
        print(f"  'mpb' or 'mockpostingbook' \t mock posting 'Credit DDA Ack' for all book transactions")

        # Non Functional Test
        print(f"NFT")
        print(f"  'nt' or 'tps' \t\t trigger TPS for given a duration")
        print(f"  'ne' or 'extraction' \t\t trigger extraction bulk TPS for given a duration")
        print(f"  'ns' or 'soak' \t\t trigger for soak test")

        # OTHERS
        print(f"Others")
        print(f"  'l' or 'load' \t\t reload json payloads")
        print(f"  'p' or 'payload' \t\t print payload for a transaction")
        print(f"  'y' or 'yaml' \t\t reload yaml config")
        print(f"  'q' or 'quit' \t\t quit program")

        x = input()
